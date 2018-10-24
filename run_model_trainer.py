#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Oct  2 13:06:33 2018

@author: simon
"""
from numpy.random import seed
seed(3)
from tensorflow import set_random_seed
set_random_seed(44)
print('Set tf seed to 44')

from trafficgraphnn.class_train_model import TrainModel

#trainer = TrainModel(data_path = 'preprocessed_data/')
trainer = TrainModel(data_path = 'data/networks/new_data/preprocessed_data/',
                     multi_gat = True)

X_train, Y_train = trainer.build_X_Y(num_simulations = 1, index_start = 0)
X_val, Y_val = trainer.build_X_Y(num_simulations = 1, index_start = 1)

#trainer.train_model(X_train, Y_train, X_val, Y_val, 
#                   simulations_per_batch = 1, 
#                   epochs = 2,
#                   es_patience = 25)

trainer.train_model_multi_gat(X_train, Y_train, X_val, Y_val, 
                   simulations_per_batch = 1, 
                   epochs = 2,
                   es_patience = 25)

trainer.save_train_model()

pred_start_index = 0
num_predictions = 2
end_index = pred_start_index + num_predictions
for pred in range(pred_start_index, end_index):
    X_predict, Y_predict = trainer.build_X_Y(num_simulations = 1, index_start = pred)
    _ = trainer.predict_on_best_model(X_predict, Y_predict, prediction_number = pred)

