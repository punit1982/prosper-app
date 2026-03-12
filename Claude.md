{\rtf1\ansi\ansicpg1252\cocoartf2868
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # Project Prosper: The AI-Native Investment Operating System\
\
## 1. Vision\
Prosper is a global, unified investment dashboard designed for high-net-worth individuals and institutional client management. It solves the "fragmented data" problem by allowing users to upload screenshots/PDFs from any global broker (IBKR, Zerodha, HSBC, Tiger, etc.) and transforming that data into a CIO-level analytical suite.\
\
## 2. Technical Strategy (Phase 1 MVP)\
- **Primary Goal:** Quickest path to value via "Manual Ingestion" (Screenshots/PDFs).\
- **Core Stack:** Python + Streamlit (UI), SQLite (Local Data), Claude 3.5/4.5 (Vision & Analysis).\
- **Security:** All financial data stays local. API keys must be stored in a `.env` file (never hardcoded).\
\
## 3. MVP Features to Build Immediately\
1. **The 'Prosper Portal' (UI):** A clean, professional sidebar for uploading images and a main dashboard for the portfolio table.\
2. **Screenshot Parser:** An AI agent that reads brokerage images and extracts: \{Ticker, Name, Quantity, Average Cost, Currency\}.\
3. **The 'CIO Engine':** For every extracted stock, fetch live price and basic health metrics (ROIC, P/E, Debt-to-Equity) using the Financial Modeling Prep (FMP) API.\
4. **Currency Normalizer:** Convert all global holdings into a single 'Base Currency' (defaulting to USD or AED).\
\
## 4. Operational Guardrails for Claude Code\
- **Non-Coder Friendly:** The user is the Product Lead, not a developer. Explain what you are doing in plain English before writing code.\
- **Robustness:** If a screenshot is unreadable, provide a clear explanation of why (e.g., "Image too blurry" or "Data columns not found").\
- **Local First:** Prioritize speed and privacy. Use SQLite for the database.}