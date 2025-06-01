import alpaca_trade_api as tradeapi
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
from app.core.config import settings
from app.models.models import Trade
from sqlalchemy.orm import Session

class TradingService:
    def __init__(self, api_key: str, secret_key: str, base_url: str):
        self.api = tradeapi.REST(api_key, secret_key, base_url)
        
    def get_account(self) -> Dict:
        """Get account information"""
        return self.api.get_account()
    
    def get_portfolio_value(self) -> float:
        """Get current portfolio value"""
        account = self.get_account()
        return float(account.equity)
    
    def get_positions(self) -> List[Dict]:
        """Get current positions"""
        positions = self.api.list_positions()
        return [{
            'symbol': pos.symbol,
            'qty': float(pos.qty),
            'avg_entry_price': float(pos.avg_entry_price),
            'current_price': float(pos.current_price),
            'market_value': float(pos.market_value),
            'unrealized_pl': float(pos.unrealized_pl)
        } for pos in positions]
    
    def place_order(self, symbol: str, qty: float, side: str, 
                   order_type: str = 'market', time_in_force: str = 'day',
                   limit_price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> Dict:
        """Place a new order"""
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price,
                stop_price=stop_price
            )
            return {
                'id': order.id,
                'symbol': order.symbol,
                'qty': float(order.qty),
                'side': order.side,
                'type': order.type,
                'status': order.status
            }
        except Exception as e:
            raise Exception(f"Error placing order: {str(e)}")
    
    def get_historical_data(self, symbol: str, timeframe: str = '1D',
                          start_date: Optional[datetime] = None,
                          end_date: Optional[datetime] = None) -> pd.DataFrame:
        """Get historical price data"""
        if not start_date:
            start_date = datetime.now() - timedelta(days=365)
        if not end_date:
            end_date = datetime.now()
            
        bars = self.api.get_bars(
            symbol,
            timeframe,
            start=start_date.isoformat(),
            end=end_date.isoformat()
        ).df
        
        return bars
    
    def calculate_position_size(self, symbol: str, risk_per_trade: float = 0.02) -> float:
        """Calculate position size based on risk management"""
        account = self.get_account()
        portfolio_value = float(account.equity)
        risk_amount = portfolio_value * risk_per_trade
        
        # Get current price
        quote = self.api.get_latest_quote(symbol)
        current_price = float(quote.ask_price)
        
        # Calculate position size
        position_size = risk_amount / current_price
        
        # Round to appropriate decimal places
        return round(position_size, 2)
    
    def execute_trade(self, db: Session, user_id: int, symbol: str, 
                     prediction: float, confidence: float) -> Trade:
        """Execute trade based on ML prediction"""
        # Calculate position size
        qty = self.calculate_position_size(symbol)
        
        # Determine trade direction
        side = 'buy' if prediction > 0 else 'sell'
        
        # Place order
        order = self.place_order(symbol, qty, side)
        
        # Create trade record
        trade = Trade(
            user_id=user_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=float(order.get('price', 0)),
            status=order['status'],
            order_type='market',
            strategy='ml_prediction'
        )
        
        db.add(trade)
        db.commit()
        db.refresh(trade)
        
        return trade
    
    def get_trade_history(self, start_date: Optional[datetime] = None,
                         end_date: Optional[datetime] = None) -> List[Dict]:
        """Get trade history"""
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()
            
        trades = self.api.get_activities(
            start=start_date.isoformat(),
            end=end_date.isoformat()
        )
        
        return [{
            'id': trade.id,
            'symbol': trade.symbol,
            'qty': float(trade.qty),
            'side': trade.side,
            'price': float(trade.price),
            'status': trade.status,
            'created_at': trade.created_at
        } for trade in trades] 