# EagleEyesAI

## InvestmentDashboard

A local, single-user portfolio research sandbox. Prediction-market probabilities set macro scenario weights; existing company research and an explainable statistical model test portfolio alternatives against those scenarios.

The app does not connect to a broker, submit trades, or claim to produce a best portfolio.

## Start locally

From this folder, install the two runtimes once:

```bash
npm install
../.venv/bin/python -m pip install -r backend/requirements.txt
```

Then start both the local API and dashboard:

```bash
npm run local
```

Open `http://localhost:3000`. Portfolio data and saved analyses are stored only in `data/dashboard.db` inside this folder.

## Optional explanations

Calculations do not require an LLM. Choose Template only, Local Ollama, or an OpenAI-compatible endpoint in Optimize. For an authenticated compatible endpoint, set `DASHBOARD_LLM_API_KEY` in the API process environment. The key is never stored in the dashboard database.

## CSV format

Required: `ticker` plus one of `shares`, `weight`, or `market_value`.

Optional: `cost_basis`, `account_type`, and `acquisition_date`.
