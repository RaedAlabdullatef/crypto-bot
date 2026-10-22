import ccxt
import pandas as pd
import os

# 1. جلب البيانات الحية من منصة Kraken
exchange = ccxt.kraken({'enableRateLimit': True})
symbol = 'BTC/USD'
timeframe = '1d'

print("جاري جلب البيانات من منصة Kraken...")
ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

# 2. حساب المتوسطات المتحركة (MA20 و MA50)
df['MA20'] = df['close'].rolling(20).mean()
df['MA50'] = df['close'].rolling(50).mean()

# 3. تحديد الإشارة
df['signal'] = (df['MA20'] > df['MA50']).astype(int)
df['position'] = df['signal'].shift(1).fillna(0)

# 4. محاكاة رأس المال (Paper Trading)
initial_cash = 1000.0
fee = 0.001  # 0.1% رسوم التداول

df['market_return'] = df['close'].pct_change().fillna(0)
df['trade_change'] = df['position'].diff().abs().fillna(df['position'].abs())

df['strategy_return'] = (df['position'] * df['market_return']) - (df['trade_change'] * fee)
df['equity'] = initial_cash * (1 + df['strategy_return']).cumprod()

# 5. استخراج القيم الحالية
current_equity = df['equity'].iloc[-1]
current_price = df['close'].iloc[-1]
current_date = str(df['timestamp'].iloc[-1].date())
current_position_code = df['position'].iloc[-1]
current_position_text = "مستثمر في البيتكوين (Long)" if current_position_code == 1 else "كاش (Cash)"

print("="*40)
print(f"💰 رأس المال الوهمي الحالي: ${current_equity:,.2f}")
print(f"📈 سعر البيتكوين الحالي:   ${current_price:,.2f}")
print(f"🤖 حالة المركز الحالية:    {current_position_text}")
print("="*40)

# 6. حفظ النتيجة في ملف سجل (CSV)
log_file = 'bot_trading_log.csv'
new_log = pd.DataFrame({
    'Date': [current_date],
    'Price': [current_price],
    'Equity': [current_equity],
    'Position': [current_position_text]
})

if not os.path.exists(log_file):
    new_log.to_csv(log_file, index=False)
    print("📁 تم إنشاء سجل جديد وحفظ البيانات فيه.")
else:
    existing_logs = pd.read_csv(log_file)
    # إضافة السطر الجديد مباشرة
    updated_logs = pd.concat([existing_logs, new_log], ignore_index=True)
    # إزالة التكرار إن وجد لنفس اليوم
    updated_logs = updated_logs.drop_duplicates(subset=['Date'], keep='last')
    updated_logs.to_csv(log_file, index=False)
    print("📁 تم تحديث سجل التداولات بنجاح.")
