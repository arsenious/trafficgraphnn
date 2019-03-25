import argparse
import json
import logging
import os
import re

import numpy as np
import tensorflow as tf

from keras.layers import Dense, Dropout, Input, TimeDistributed
from keras.models import Model
from trafficgraphnn import SumoNetwork
from trafficgraphnn.custom_fit_loop import predict_eval_tf
from trafficgraphnn.layers import ReshapeFoldInLanes, ReshapeUnfoldLanes
from trafficgraphnn.load_data_tf import TFBatcher
from trafficgraphnn.losses import (huber, negative_masked_huber,
                                   negative_masked_mae, negative_masked_mape,
                                   negative_masked_mse)
from trafficgraphnn.nn_modules import (gat_encoder, output_tensor_slices,
                                       rnn_attn_decode, rnn_encode)

_logger = logging.getLogger(__name__)


def main(
    net_name,
    model_dir,
    batch_size=None,
    val_split_proportion=.2,
    seed=123,
):

    tf.set_random_seed(seed)
    np.random.seed(seed)

    net_dir = os.path.join('data', 'networks', net_name)

    sn = SumoNetwork.from_preexisting_directory(net_dir)
    lanes = sn.lanes_with_detectors()
    num_lanes = len(lanes)

    data_dir = os.path.join(net_dir, 'preprocessed_data')

    # load hyperparams
    with open(os.path.join(model_dir, 'params.json'), 'r') as f:
        hparams = json.load(f)

    A_name_list = hparams['A_name_list']
    attn_dim = hparams['attn_dim']
    dropout_rate = hparams['dropout_rate']
    attn_dropout = hparams['attn_dropout']
    attn_residual_connection = hparams.get('attn_residual_connection', False)
    dense_dim = hparams['dense_dim']
    stateful_rnn = hparams.get('stateful_rnn', True)
    rnn_dim = hparams['rnn_dim']
    attn_heads = hparams.get('attn_heads', [dense_dim // attn_dim[0]]*3)
    if batch_size is None:
        batch_size = hparams['batch_size']
    loss_function = hparams['loss_function']
    x_feature_subset = hparams.get('x_feature_subset', ['e1_0/occupancy',
                                                        'e1_0/speed',
                                                        'e1_1/occupancy',
                                                        'e1_1/speed',
                                                        'liu_estimated_veh',
                                                        'green'])
    y_feature_subset = hparams.get(
        'y_feature_subset', ['e2_0/nVehSeen', 'e2_0/maxJamLengthInVehicles'])

    with tf.device('/cpu:0'):
        batch_gen = TFBatcher(data_dir,
                              batch_size,
                              hparams['time_window'],
                              average_interval=hparams['average_interval'],
                              val_proportion=val_split_proportion,
                              shuffle=False,
                              A_name_list=hparams['A_name_list'],
                              x_feature_subset=x_feature_subset,
                              y_feature_subset=y_feature_subset,
                              )

        Xtens = batch_gen.X
        Atens = tf.cast(batch_gen.A, tf.float32)
        Ytens = batch_gen.Y_slices

    model_dir_files = os.listdir(model_dir)
    regexped = [re.search(r'(?<=epoch)\d+(?=-)', f) for f in model_dir_files]
    file_epochs = {
        int(r[0]): f for r, f in zip(regexped, model_dir_files) if r is not None
    }
    last_epoch = sorted(list(file_epochs.keys()))[-1]
    weights_filename = os.path.join(model_dir, file_epochs[last_epoch])

    if loss_function.lower() == 'mse':
        losses = ['mse', negative_masked_mse]
        metrics = [negative_masked_mae, negative_masked_huber,
                negative_masked_mape]
    elif loss_function.lower() == 'mae':
        losses = ['mae', negative_masked_mae]
        metrics = [negative_masked_mse, negative_masked_huber,
                negative_masked_mape]
    elif loss_function.lower() == 'huber':
        losses = [huber, negative_masked_huber]
        metrics = [negative_masked_mse, negative_masked_mae,
                negative_masked_mape]

    # X dimensions: timesteps x lanes x feature dim
    X_in = Input(batch_shape=(None, None, num_lanes, len(x_feature_subset)),
                 name='X', tensor=Xtens)
    # A dimensions: timesteps x lanes x lanes
    A_in = Input(batch_shape=(None, None, len(A_name_list),
                              num_lanes, num_lanes),
                 name='A', tensor=Atens)

    def make_model(X_in, A_in):
        X = gat_encoder(X_in, A_in, attn_dim, attn_heads,
                        dropout_rate, attn_dropout, gat_activation='relu',
                        residual_connection=attn_residual_connection)

        predense = TimeDistributed(Dropout(dropout_rate))(X)

        dense1 = TimeDistributed(Dense(dense_dim, activation='relu'))(predense)

        if stateful_rnn:
            reshape_batch_size = batch_size
        else:
            reshape_batch_size = None
        reshaped_1 = ReshapeFoldInLanes(batch_size=reshape_batch_size)(dense1)

        encoded = rnn_encode(reshaped_1, [rnn_dim], 'GRU',
                             stateful=stateful_rnn)

        decoded = rnn_attn_decode('GRU', rnn_dim, encoded,
                                  stateful=stateful_rnn)

        reshaped_decoded = ReshapeUnfoldLanes(num_lanes)(decoded)
        output = TimeDistributed(
            Dense(len(y_feature_subset), activation='relu'))(reshaped_decoded)

        outputs = output_tensor_slices(output, y_feature_subset)

        model = Model([X_in, A_in], outputs)
        return model

    model = make_model(X_in, A_in)
    model.compile(optimizer='Adam',
                  loss=losses,
                  metrics=metrics,
                  target_tensors=Ytens,
                  )

    model.load_weights(weights_filename)

    predict_eval_tf(model, model_dir, batch_gen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('net_name', type=str, help='Name of Sumo Network')
    parser.add_argument('model_dir', type=str, help='Directory to saved model')
    parser.add_argument('--batch_size', '-b', type=int,
                        help='Evaluation batch size')
    parser.add_argument('--val_split', '-v', type=float, default=.2,
                        help='Data proportion to use for validation')
    parser.add_argument('--seed', '-s', type=int, help='Random seed',
                        default=123)
    args = parser.parse_args()

    main(args.net_name,
         args.model_dir,
         batch_size=args.batch_size,
         val_split_proportion=args.val_split,
         seed=args.seed,
         )
