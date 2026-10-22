import ccxt
import pandas as pd
import os
import urllib.request
import urllib.parse

# دالة إرسال التنبيه إلى تليجرام
def send_telegram_message(message):
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("⚠️ مفاتيح تليجرام غير متوفرة، تم تخطي إرسال الرسالة.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': message}).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req) as response:
            print("📲 تم إرسال تنبيه تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ فشل إرسال تنبيه تليجرام: {e}")

# 1. جلب البيانات من منصة Kraken
exchange = ccxt.kraken({'enableRateLimit': True})
symbol = 'BTC/USD'
timeframe = '1d'

print("جاري جلب البيانات من منصة Kraken...")
ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

# 2. حساب المتوسطات المتحركة
df['MA20'] = df['close'].rolling(20).mean()
df['MA50'] = df['close'].rolling(50).mean()

# 3. تحديد الإشارة
df['signal'] = (df['MA20'] > df['MA50']).astype(int)
df['position'] = df['signal'].shift(1).fillna(0)

# 4. محاكاة رأس المال (Paper Trading)
initial_cash = 1000.0
fee = 0.001

df['market_return'] = df['close'].pct_change().fillna(0)
df['trade_change'] = df['position'].diff().abs().fillna(df['position'].abs())

df['strategy_return'] = (df['position'] * df['market_return']) - (df['trade_change'] * fee)
df['equity'] = initial_cash * (1 + df['strategy_return']).cumprod()

# 5. القيم الحالية
current_equity = df['equity'].iloc[-1]
current_price = df['close'].iloc[-1]
current_date = str(df['timestamp'].iloc[-1].date())
current_position_code = df['position'].iloc[-1]
current_position_text = "مستثمر في البيتكوين (Long) 📈" if current_position_code == 1 else "كاش / خروج (Cash) 💵"

# إعداد نص الرسالة
msg = (
    f"🤖 تقرير بوت التداول اليومي\n"
    f"━━━━━━━━━━━━━━━━━━\n"
    f"📅 التاريخ: {current_date}\n"
    f"💰 سعر البيتكوين: ${current_price:,.2f}\n"
    f"📊 رأس المال الحالي: ${current_equity:,.2f}\n"
    f"🎯 حالة المركز: {current_position_text}"
)

# إرسال التنبيه
send_telegram_message(msg)

# 6. حفظ النتيجة في ملف CSV
log_file = 'bot_trading_log.csv'
new_log = pd.DataFrame({
    'Date': [current_date],
    'Price': [current_price],
    'Equity': [current_equity],
    'Position': [current_position_text]
})

if not os.path.exists(log_file):
    new_log.to_csv(log_file, index=False)
else:
    existing_logs = pd.read_csv(log_file)
    updated_logs = pd.concat([existing_logs, new_log], ignore_index=True)
    updated_logs = updated_logs.drop_duplicates(subset=['Date'], keep='last')
    updated_logs.to_csv(log_file, index=False)
