import ccxt
import pandas as pd
import os
import json
import urllib.request
import urllib.parse

# ============ الإعدادات (عدّلها بسهولة من هنا) ============
SYMBOLS = [
    'BTC/USD', 'ETH/USD', 'SOL/USD', 'XRP/USD', 'ADA/USD',
    'AVAX/USD', 'DOT/USD', 'LINK/USD', 'LTC/USD', 'NEAR/USD'
]
TIMEFRAME = '1d'
INITIAL_CASH = 1000.0
FEE_RATE = 0.0026            # عمولة Kraken التقريبية لكل صفقة (0.26%)
STOP_LOSS = 0.08             # وقف خسارة 8% من سعر الدخول
RSI_PERIOD = 14
RSI_MAX_ENTRY = 75           # لا ندخل عملة تشبّعها الشرائي أعلى من هذا
REQUIRE_PRICE_ABOVE_MA20 = True
SWITCH_MARGIN = 1.0          # لا نبدّل العملة إلا إذا تفوقت الجديدة بهذا الهامش (نقطة مئوية)
STATE_FILE = 'bot_state.json'
LOG_FILE = 'bot_trading_log.csv'
BENCHMARK = 'BTC/USD'


# ============ تليجرام ============
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
        with urllib.request.urlopen(req, timeout=20):
            print("📲 تم إرسال تنبيه تليجرام بنجاح!")
    except Exception as e:
        print(f"❌ فشل إرسال تنبيه تليجرام: {e}")


# ============ المؤشرات والتحليل ============
def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float('nan'))
    return (100 - 100 / (1 + rs)).fillna(100)


def analyze(exchange, symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=120)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df.iloc[:-1]  # حذف الشمعة الحالية غير المكتملة، نعتمد الشموع المغلقة فقط
    if len(df) < 51:
        return None

    df['MA20'] = df['close'].rolling(20).mean()
    df['MA50'] = df['close'].rolling(50).mean()
    df['RSI'] = calc_rsi(df['close'], RSI_PERIOD)

    close = float(df['close'].iloc[-1])
    ma20 = float(df['MA20'].iloc[-1])
    ma50 = float(df['MA50'].iloc[-1])
    rsi = float(df['RSI'].iloc[-1])

    trend_ok = ma20 > ma50 and (close > ma20 if REQUIRE_PRICE_ABOVE_MA20 else True)
    score = (ma20 - ma50) / ma50 * 100

    return {'close': close, 'ma20': ma20, 'ma50': ma50,
            'rsi': rsi, 'score': score, 'trend_ok': trend_ok}


def live_price(exchange, symbol):
    return float(exchange.fetch_ticker(symbol)['last'])


# ============ الحالة (المحفظة الافتراضية) ============
def load_state():
    default = {
        'cash': INITIAL_CASH, 'symbol': None, 'qty': 0.0,
        'entry_price': 0.0, 'cost': 0.0, 'entry_date': None,
        'trades': 0, 'benchmark_start': None
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                default.update(json.load(f))
        except Exception as e:
            print(f"تعذّر قراءة ملف الحالة، سيتم البدء من جديد: {e}")
    return default


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def do_sell(state, price, reason, date):
    proceeds = state['qty'] * price * (1 - FEE_RATE)
    pnl = proceeds - state['cost']
    pnl_pct = pnl / state['cost'] * 100 if state['cost'] else 0.0
    msg = f"🔴 بيع {state['symbol']} @ {price:,.4f} ({reason}) | الربح/الخسارة: {pnl_pct:+.2f}% (${pnl:+,.2f})"
    state.update({'cash': proceeds, 'symbol': None, 'qty': 0.0,
                  'entry_price': 0.0, 'cost': 0.0, 'entry_date': None})
    state['trades'] += 1
    return msg


def do_buy(state, symbol, price, date):
    spend = state['cash']
    state['qty'] = spend * (1 - FEE_RATE) / price
    state['cost'] = spend
    state.update({'cash': 0.0, 'symbol': symbol,
                  'entry_price': price, 'entry_date': date})
    state['trades'] += 1
    return f"🟢 شراء {symbol} @ {price:,.4f}"


# ============ البرنامج الرئيسي ============
def main():
    exchange = ccxt.kraken({'enableRateLimit': True})
    state = load_state()
    current_date = str(pd.Timestamp.now(tz='UTC').date())

    print("🔎 جاري مسح وتحليل جميع العملات المحددة...")
    analysis = {}
    for symbol in SYMBOLS:
        try:
            analysis[symbol] = analyze(exchange, symbol)
        except Exception as e:
            print(f"خطأ في جلب بيانات {symbol}: {e}")

    # تقييم المركز الحالي بالسعر الحي
    held = state['symbol']
    held_price = None
    if held:
        try:
            held_price = live_price(exchange, held)
        except Exception as e:
            send_telegram_message(f"⚠️ تعذّر جلب سعر {held}، تم تخطي تشغيل اليوم.\n{e}")
            return

    candidates = sorted(
        [(s, a) for s, a in analysis.items()
         if a and a['trend_ok'] and a['rsi'] < RSI_MAX_ENTRY],
        key=lambda x: x[1]['score'], reverse=True
    )

    actions = []
    blocked = set()

    # --- قرار الخروج / التدوير ---
    if held:
        a = analysis.get(held)
        if held_price <= state['entry_price'] * (1 - STOP_LOSS):
            actions.append(do_sell(state, held_price, 'وقف الخسارة', current_date))
            blocked.add(held)
        elif a and not a['trend_ok']:
            actions.append(do_sell(state, held_price, 'كسر الاتجاه', current_date))
        elif (a and candidates and candidates[0][0] != held
              and candidates[0][1]['score'] > a['score'] + SWITCH_MARGIN):
            actions.append(do_sell(state, held_price, 'تدوير لعملة أقوى', current_date))

    # --- قرار الدخول ---
    if state['symbol'] is None:
        for symbol, a in candidates:
            if symbol in blocked:
                continue
            try:
                price = live_price(exchange, symbol)
            except Exception:
                price = a['close']
            actions.append(do_buy(state, symbol, price, current_date))
            break

    # --- حساب رأس المال الحالي ---
    if state['symbol']:
        cur_price = held_price if state['symbol'] == held and held_price else None
        if cur_price is None:
            try:
                cur_price = live_price(exchange, state['symbol'])
            except Exception:
                cur_price = state['entry_price']
        equity = state['qty'] * cur_price
        pos_pnl = (cur_price / state['entry_price'] - 1) * 100
        position_text = (f"{state['symbol']} | دخول {state['entry_price']:,.4f} "
                         f"| الآن {cur_price:,.4f} ({pos_pnl:+.2f}%)")
        logged_symbol, logged_price = state['symbol'], cur_price
    else:
        equity = state['cash']
        position_text = "كاش 💵"
        logged_symbol, logged_price = "NONE", 0.0

    total_return = (equity / INITIAL_CASH - 1) * 100

    # --- مقارنة مع الاحتفاظ بـ BTC ---
    bench_text = ""
    try:
        btc_now = live_price(exchange, BENCHMARK)
        if not state['benchmark_start']:
            state['benchmark_start'] = btc_now
        bench_ret = (btc_now / state['benchmark_start'] - 1) * 100
        bench_text = f"\n₿ الاحتفاظ بـ BTC منذ البداية: {bench_ret:+.2f}%"
    except Exception:
        pass

    save_state(state)

    # --- الرسالة ---
    top_lines = ""
    for s, a in candidates[:3]:
        top_lines += f"\n   • {s}: قوة {a['score']:+.2f}% | RSI {a['rsi']:.0f}"
    if not top_lines:
        top_lines = "\n   لا توجد عملات مؤهلة حالياً"

    actions_text = "\n".join(actions) if actions else "⏸️ لا تغيير (احتفاظ بالمركز الحالي)"

    msg = (
        f"🤖 تقرير البوت اليومي\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 التاريخ: {current_date}\n"
        f"🔍 فُحصت {len(analysis)}/{len(SYMBOLS)} عملة | مؤهلة: {len(candidates)}\n"
        f"🏆 أفضل المرشحين:{top_lines}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ الإجراءات:\n{actions_text}\n"
        f"📌 المركز الحالي: {position_text}\n"
        f"💰 رأس المال: ${equity:,.2f} ({total_return:+.2f}% منذ البداية)"
        f"{bench_text}\n"
        f"🔁 عدد الصفقات: {state['trades']}"
    )
    print(msg)
    send_telegram_message(msg)

    # --- السجل ---
    new_log = pd.DataFrame({
        'Date': [current_date],
        'Selected_Symbol': [logged_symbol],
        'Price': [logged_price],
        'Equity': [round(equity, 2)],
        'Position': [position_text],
        'Action': [" / ".join(actions) if actions else "HOLD"],
    })
    if os.path.exists(LOG_FILE):
        try:
            logs = pd.concat([pd.read_csv(LOG_FILE), new_log], ignore_index=True)
        except Exception:
            logs = new_log
        logs = logs.drop_duplicates(subset=['Date'], keep='last')
    else:
        logs = new_log
    logs.to_csv(LOG_FILE, index=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        send_telegram_message(f"❌ خطأ غير متوقع في البوت:\n{e}")
        raise
