# -*- coding: utf-8 -*-
"""
Sustainblop: Production-Grade Stock Price Prediction with ESG Integration

This Streamlit app downloads historical stock data from yFinance, trains a deep learning
model (using GRU layers), and predicts future stock prices. It also incorporates ESG scores,
which are used to rank stocks.
"""

import os
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import streamlit as st
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, GRU, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.preprocessing import MinMaxScaler  # Required import for scaling

# Set page configuration for Streamlit
st.set_page_config(
    page_title="Stock Price Prediction with ESG Integration",
    layout="wide",
)

# Check if ESG CSV file exists or create dummy data.
# We wrap this in a try/except so that error messages are friendly in Streamlit.
esg_file_path = 'esg_data.csv'
if os.path.exists(esg_file_path):
    try:
        esg_data = pd.read_csv(esg_file_path)
        st.info(f"Loaded ESG data from: {esg_file_path}")
    except Exception as e:
        st.error(f"Error reading {esg_file_path}: {e}")
        esg_data = pd.DataFrame({
            'ticker': ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META'],
            'total_score': [80, 85, 75, 90, 70]
        })
else:
    st.warning(f"CSV file '{esg_file_path}' not found. Using dummy ESG data.")
    esg_data = pd.DataFrame({
        'ticker': ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META'],
        'total_score': [80, 85, 75, 90, 70]
    })

def create_dataset(dataset, time_step=1):
    """
    Generates X and y datasets from a multi-feature time-series dataset.
    In this implementation, we predict the 'Close' price (index 3).
    """
    X, Y = [], []
    for i in range(len(dataset) - time_step - 1):
        X.append(dataset[i:(i + time_step)])
        Y.append(dataset[i + time_step, 3])  # Assumes index 3 corresponds to 'Close'
    return np.array(X), np.array(Y)

def predict_future(model, data, days_to_predict, time_step):
    """
    Predict future stock prices given the last `time_step` days' data.
    The model output is used to update the input window on each iteration.
    """
    last_window = data[-time_step:].reshape(1, time_step, data.shape[1])
    future_predictions = []
    for _ in range(days_to_predict):
        next_pred = model.predict(last_window, verbose=0)
        future_predictions.append(next_pred[0, 0])
        # Update the window: append the predicted value (update only the 'Close' feature).
        next_row = last_window[0, -1].copy()
        next_row[3] = next_pred  # Only updating index 3 ('Close')
        last_window = np.append(last_window[:, 1:, :], next_row.reshape(1, -1, data.shape[1]), axis=1)
    return np.array(future_predictions).reshape(-1, 1)

def load_model_and_data(tickers, esg_data):
    """
    For each ticker:
      - Download historical stock data from yFinance.
      - Scale data and split into training and testing sets.
      - Create and train a GRU-based model.
      - Calculate prediction accuracy metrics (RMSE and MAE).
    Returns dictionaries for original data, scaled data, scalers, models, ESG scores, and accuracy metrics.
    """
    data = {}
    scaled_data = {}
    scalers = {}
    models = {}
    accuracies = {}
    # Convert ESG dataframe to dictionary for quick lookup.
    esg_scores = esg_data.set_index('ticker')['total_score'].to_dict()

    for ticker in tickers:
        try:
            stock_data = yf.download(ticker, start="2010-01-01", end="2023-12-31", progress=False)
            if not stock_data.empty:
                df = stock_data[['Open', 'High', 'Low', 'Close', 'Volume']]
                dataset = df.values  # Shape: (n_samples, 5)
                scaler = MinMaxScaler(feature_range=(0, 1))
                scaled = scaler.fit_transform(dataset)
                data[ticker] = dataset
                scaled_data[ticker] = scaled
                scalers[ticker] = scaler

                # Split data (65% training, 35% testing)
                training_size = int(len(scaled) * 0.65)
                train_data = scaled[:training_size, :]
                test_data = scaled[training_size:, :]

                time_step = 100
                X_train, y_train = create_dataset(train_data, time_step)
                X_test, y_test = create_dataset(test_data, time_step)

                input_features = train_data.shape[1]  # Should be 5 in our case.
                # Reshape to (samples, time_step, features)
                X_train = X_train.reshape(X_train.shape[0], time_step, input_features)
                X_test = X_test.reshape(X_test.shape[0], time_step, input_features)

                # Build the GRU-based model.
                model = Sequential()
                model.add(GRU(50, return_sequences=True, input_shape=(time_step, input_features)))
                model.add(Dropout(0.2))
                model.add(GRU(50, return_sequences=True))
                model.add(Dropout(0.2))
                model.add(GRU(50))
                model.add(Dropout(0.2))
                model.add(Dense(1))
                model.compile(loss='mean_squared_error', optimizer='adam')

                # Use EarlyStopping to prevent overfitting.
                early_stop = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
                model.fit(X_train, y_train, validation_data=(X_test, y_test),
                          epochs=50, batch_size=128, callbacks=[early_stop], verbose=0)
                models[ticker] = model

                # Compute accuracy metrics.
                y_pred = model.predict(X_test, verbose=0)
                # Inverse transform: build a temporary array to replace the 'Close' column with predictions.
                y_test_inv = scalers[ticker].inverse_transform(
                    np.hstack([X_test[:, -1, :3], y_test.reshape(-1, 1), X_test[:, -1, 4].reshape(-1, 1)])
                )[:, 3]  # Extract inverse-transformed 'Close' price.
                y_pred_inv = scalers[ticker].inverse_transform(
                    np.hstack([X_test[:, -1, :3], y_pred, X_test[:, -1, 4].reshape(-1, 1)])
                )[:, 3]
                rmse = np.sqrt(mean_squared_error(y_test_inv, y_pred_inv))
                mae = mean_absolute_error(y_test_inv, y_pred_inv)
                accuracies[ticker] = {'RMSE': rmse, 'MAE': mae}
            else:
                st.warning(f"No data available for {ticker}")
        except Exception as e:
            st.error(f"Error processing {ticker}: {str(e)}")
    return data, scaled_data, scalers, models, esg_scores, accuracies

def show_stock_price_prediction_page():
    """
    Main function to display the Streamlit page.
    Users can input tickers, select prediction period, adjust weightings, and view predictions.
    """
    st.title("Production-Grade Stock Price Prediction with ESG Integration")
    st.markdown("This app predicts stock prices using a GRU-based model and ranks stocks using ESG scores.")

    # User input for tickers.
    tickers_input = st.text_input("Enter stock tickers (comma separated):", "AAPL, MSFT, AMZN, GOOGL, META")
    tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
    
    # Select prediction period.
    period = st.selectbox("Select prediction period:", ("3 months", "6 months", "1 year"))
    days_to_predict = {"3 months": 90, "6 months": 180, "1 year": 365}[period]
    
    # Adjust the weight between predicted price and ESG score.
    price_weight = st.slider("Price-ESG weight:", 0.0, 1.0, 0.5)
    esg_weight = 1 - price_weight

    if st.button("Get Predictions"):
        if not tickers:
            st.error("Please enter at least one ticker.")
            return

        # Load data, models, and ESG scores.
        data, scaled_data, scalers, models, esg_scores, accuracies = load_model_and_data(tickers, esg_data)
        if not models:
            st.error("Failed to load models or data for the provided tickers.")
            return

        predictions_dict = {}
        for ticker in tickers:
            if ticker in scaled_data:
                time_step = 100
                future_predictions = predict_future(models[ticker], scaled_data[ticker], days_to_predict, time_step)
                # Inverse transformation for the predicted 'Close' price.
                actual_predictions = scalers[ticker].inverse_transform(
                    np.hstack([
                        scaled_data[ticker][-time_step:, :3],
                        future_predictions,
                        scaled_data[ticker][-time_step:, 4].reshape(-1, 1)
                    ])
                )[:, 3]
                predictions_dict[ticker] = actual_predictions

                st.subheader(f"Predicted stock prices for {ticker} for the next {period}:")
                predictions_df = pd.DataFrame({
                    "Day": range(1, len(actual_predictions) + 1),
                    "Predicted Price": actual_predictions.flatten()
                })
                st.dataframe(predictions_df)

                # Plot actual and predicted prices.
                plt.figure(figsize=(10, 5))
                plt.plot(data[ticker][:, 3], label=f"{ticker} Actual")  # Use 'Close' price.
                plt.plot(range(len(data[ticker]), len(data[ticker]) + days_to_predict),
                         actual_predictions, label=f"{ticker} Predicted ({period})")
                plt.xlabel("Days")
                plt.ylabel("Price")
                plt.title(f"Stock Price Predictions for {ticker}")
                plt.legend()
                st.pyplot(plt.gcf())
                plt.close()

                # Display accuracy metrics.
                if ticker in accuracies:
                    st.write(f"Accuracy for {ticker}: RMSE = {accuracies[ticker]['RMSE']:.2f}, MAE = {accuracies[ticker]['MAE']:.2f}")
            else:
                st.warning(f"Skipping {ticker} due to missing data.")

        # Rank stocks based on predicted profit and ESG scores.
        profit_ranks = {ticker: np.mean(predictions_dict[ticker]) for ticker in predictions_dict}
        if profit_ranks:
            norm_profit = MinMaxScaler().fit_transform(np.array(list(profit_ranks.values())).reshape(-1, 1)).flatten()
            norm_esg = MinMaxScaler().fit_transform(np.array([esg_scores.get(ticker, 0) for ticker in tickers]).reshape(-1, 1)).flatten()
            combined_ranks = {ticker: (norm_profit[i] * price_weight + norm_esg[i] * esg_weight)
                              for i, ticker in enumerate(tickers)}
            ranked_stocks = sorted(combined_ranks.items(), key=lambda x: x[1], reverse=True)
            st.subheader("Ranked Stocks based on predicted profit and ESG score:")
            for rank, (ticker, score) in enumerate(ranked_stocks, 1):
                st.write(f"{rank}. {ticker}: {score:.2f}")
        else:
            st.write("No predictions available to rank stocks.")

if __name__ == '__main__':
    show_stock_price_prediction_page()
