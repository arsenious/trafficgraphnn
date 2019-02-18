import logging
import os
import time
from collections import OrderedDict

import tensorflow as tf

import keras.backend as K
from keras.callbacks import (BaseLogger, CallbackList, History,
                             ModelCheckpoint, ProgbarLogger, ReduceLROnPlateau,
                             TensorBoard, TerminateOnNaN)

_logger = logging.getLogger(__name__)


def make_callbacks(model, model_save_dir, do_validation=False):
    callback_list = CallbackList()
    callback_list.append(BaseLogger())
    callback_list.append(History())
    callback_list.append(TerminateOnNaN())
    callback_list.append(TensorBoard())
    if do_validation:
        display_metrics = ['val_' + n for n in model.metrics_names]
        callback_list.append(ProgbarLogger('steps', stateful_metrics=display_metrics))
    else:
        display_metrics = model.metrics_names
        callback_list.append(ProgbarLogger('steps'))

    filename = 'weights_epoch{epoch:02d}-'

    for metric in display_metrics:
        add_str = '{%s:.4f}' % metric
        filename = filename + add_str
    filename = filename + '.hdf5'
    callback_list.append(ModelCheckpoint(os.path.join(model_save_dir, filename)))
    callback_list.append(ReduceLROnPlateau(verbose=1))

    callback_list.set_model(model)
    return callback_list


def set_callback_params(callbacks,
                        epochs,
                        batch_size,
                        verbose,
                        do_validation,
                        model,
                        steps=None):
    if do_validation:
        metrics = model.metrics_names + ['val_' + n for n in model.metrics_names]
    else:
        metrics = model.metrics_names
    params_dict = {
        'batch_size': batch_size,
        'epochs': epochs,
        'verbose': verbose,
        'do_validation': do_validation,
        'metrics': metrics
    }
    if steps is not None:
        params_dict['steps'] = steps
    callbacks.set_params(params_dict)


def fit_loop_init(model, callbacks):
    callbacks.on_train_begin()
    model.reset_states()
    model._make_train_function()
    model._make_test_function()


def named_logs(model, logs):
    result = {}
    for l in zip(model.metrics_names, logs):
        result[l[0]] = l[1]
    return result


def fit_loop_train_one_epoch_tf(model, callbacks, batch_generator, epoch,
                                feed_dict=None):
    raise NotImplementedError
    callbacks.on_epoch_begin(epoch)
    _logger.info('Beginning epoch %g', epoch)

    # set up bookkeeping
    batch_size = batch_generator.batch_size * batch_generator.window_size
    t_epoch_start = time.time()
    i_step = 0
    for batch in batch_generator.train_batches:
        # losses
        model.reset_states()
        batch.initialize(K.get_session(), feed_dict)

        try:
            while True:
                tstep = time.time()

                callbacks.on_batch_begin(i_step)

                logs = model.train_on_batch(x=None, y=None)
                train_step_time = time.time() - tstep

                logs = named_logs(model, logs)
                logs['size'] = batch_size
                logs['batch'] = i_step
                logs['time'] = train_step_time

                callbacks.on_batch_end(i_step, logs)
                i_step += 1
        except tf.errors.OutOfRangeError:
            # this batch of timeseries is over
            pass
        finally:
            if model.stop_training:
                break