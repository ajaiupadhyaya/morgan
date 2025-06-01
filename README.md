# 🧠 Vuoksi AI Trader

An AI-powered algorithmic trading platform that leverages machine learning, real-time financial data, and automated trade execution via the Alpaca API.

## 🚀 Features

- AI-powered trading strategies using LSTM, XGBoost, and Reinforcement Learning
- Real-time market data integration via Alpaca API
- Beautiful, modern UI with real-time dashboards and visualizations
- Paper and live trading capabilities
- Performance tracking and analytics
- Secure authentication and user management

## 🛠️ Tech Stack

### Backend
- FastAPI (Python)
- PostgreSQL
- Redis
- Celery
- MLflow
- Alpaca API
- TensorFlow/Keras
- XGBoost

### Frontend
- React
- TailwindCSS
- Framer Motion
- D3.js/Plotly

## 📋 Prerequisites

- Python 3.9+
- Node.js 16+
- PostgreSQL
- Redis
- Alpaca API credentials
- Polygon.io API key (optional)

## 🚀 Getting Started

1. Clone the repository:
```bash
git clone https://github.com/ajaiupadhyaya/morgan.git
cd morgan
```

2. Set up the backend:
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys and configuration
```

3. Set up the frontend:
```bash
cd frontend
npm install
```

4. Start the development servers:
```bash
# Terminal 1 - Backend
uvicorn app.main:app --reload

# Terminal 2 - Frontend
cd frontend
npm run dev
```

## 🔐 Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
DATABASE_URL=postgresql://user:password@localhost:5432/morgan
REDIS_URL=redis://localhost:6379
POLYGON_API_KEY=your_polygon_key
```

## 📊 Project Structure

```
morgan/
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── ml/
│   ├── models/
│   └── services/
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
├── tests/
├── .env
├── requirements.txt
└── README.md
```

## 🧪 Testing

```bash
# Run backend tests
pytest

# Run frontend tests
cd frontend
npm test
```

## 📝 License

- Frontend: MIT License
- Backend & ML Logic: Proprietary / Research-only License

## 👥 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📫 Contact

Ajai Upadhyaya - [GitHub](https://github.com/ajaiupadhyaya)

---

*Built with ❤️ for quantitative trading excellence.*