import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Google Sheets 接続設定 ---
# Secretsから情報を取得
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # Secretsの情報を辞書型にまとめる
    creds_dict = {
        "type": "service_account",
        "project_id": "hi-friends-money", 
        "private_key_id": st.secrets["PRIVATE_KEY_ID"],
        "private_key": st.secrets["PRIVATE_KEY"],
        "client_email": st.secrets["CLIENT_EMAIL"],
        "client_id": "12345",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['CLIENT_EMAIL']}"
    }
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet_url = st.secrets["SHEET_URL"]
    sheet = client.open_by_url(sheet_url).sheet1 # 1枚目のシートを使う

except Exception as e:
    st.error(f"Googleスプレッドシートへの接続に失敗しました: {e}")
    st.stop()

# --- データ読み書き関数 ---
def load_data():
    # スプレッドシートから全データを取得
    data = sheet.get_all_records()
    if not data:
        return pd.DataFrame(columns=['日時', 'タイプ', '対象者', '金額', 'メモ'])
    return pd.DataFrame(data)

def save_record(record_dict):
    # スプレッドシートの末尾に1行追加
    # record_dictの順番を固定する
    row = [
        record_dict['日時'],
        record_dict['タイプ'],
        record_dict['対象者'],
        record_dict['金額'],
        record_dict['メモ']
    ]
    sheet.append_row(row)

# --- 初期設定 ---
if 'users' not in st.session_state:
    st.session_state.users = ["自分(B)", "友達(C)"]
if 'lender_name' not in st.session_state:
    st.session_state.lender_name = "Aさん"

# --- データをロード ---
# アプリを開くたびに最新をシートから取ってくる
df_trans = load_data()

# --- 関数：履歴に「取引後残高」を計算して付与する ---
def get_history_with_balance(df):
    if df.empty:
        return df
    
    df['日時'] = pd.to_datetime(df['日時'])
    df = df.sort_values('日時')
    
    current_balances = {user: 0 for user in st.session_state.users}
    balance_after = []
    
    for _, row in df.iterrows():
        name = row['対象者']
        if name not in current_balances:
            current_balances[name] = 0
        current_balances[name] += row['金額']
        balance_after.append(current_balances[name])
    
    df['取引後残高'] = balance_after
    return df.sort_values('日時', ascending=False)

# --- サイドバー：設定エリア ---
st.sidebar.title("⚙️ 設定・メンバー管理")

# 1. 貸し手の名前変更
st.sidebar.subheader("貸している人の名前")
new_lender_name = st.sidebar.text_input("貸し手 (ハブ役)", value=st.session_state.lender_name)
if new_lender_name != st.session_state.lender_name:
    st.session_state.lender_name = new_lender_name
    st.rerun()

st.sidebar.markdown("---")
# 2. 借り手の名前変更
st.sidebar.subheader("借りている人の名前")
st.sidebar.caption("※名前を変えても過去の履歴の名前は変わりません")
for i, old_name in enumerate(st.session_state.users):
    new_name = st.sidebar.text_input(f"メンバー {i+1}", value=old_name, key=f"user_input_{i}")
    if new_name != old_name:
        st.session_state.users[i] = new_name
        st.rerun()

# メンバー追加
new_member = st.sidebar.text_input("新規メンバー追加")
if st.sidebar.button("追加"):
    if new_member and new_member not in st.session_state.users:
        st.session_state.users.append(new_member)
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("修正・データ管理")

# 最新の履歴を1件削除
if st.sidebar.button("🗑️ 最新の履歴を1件削除"):
    all_values = sheet.get_all_values()
    if len(all_values) > 1: # ヘッダー以外にデータがある場合
        last_row_index = len(all_values)
        sheet.delete_rows(last_row_index)
        st.sidebar.success("最新の1行をスプレッドシートから削除しました。")
        st.rerun()
    else:
        st.sidebar.warning("削除するデータがありません。")

st.sidebar.markdown("---")
if st.sidebar.button("💰 今の借金をすべて0にする (清算)"):
    current_balances = {user: 0 for user in st.session_state.users}
    for _, row in df_trans.iterrows():
        name = row['対象者']
        if name in current_balances:
            current_balances[name] += row['金額']
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cnt = 0
    for user, bal in current_balances.items():
        if bal != 0:
            record = {
                '日時': now, 'タイプ': '清算/リセット', 
                '対象者': user, '金額': -bal, 'メモ': '一括清算（履歴保存）'
            }
            save_record(record)
            cnt += 1
    
    if cnt > 0:
        st.sidebar.success("全員の借金を0円にリセットしました。")
        st.rerun()
    else:
        st.sidebar.info("借金は既に0円です。")

# --- メインエリア ---
lender = st.session_state.lender_name
st.title(f"💰 {lender} 経由の借金管理")
st.caption("☁️ Googleスプレッドシート連携中")

# 現在の状況計算
balance = {user: 0 for user in st.session_state.users}
for _, row in df_trans.iterrows():
    name = row['対象者']
    if name in balance:
        balance[name] += row['金額']

df_balance = pd.DataFrame(list(balance.items()), columns=['名前', '借金残高'])
total_lent = df_balance['借金残高'].sum()

# 合計表示
col1, col2 = st.columns(2)
col1.metric(f"{lender} が貸している総額", f"{total_lent:,} 円")
col2.info("入力したデータは自動的にGoogleスプレッドシートに保存されます。")

# グラフ表示
if total_lent != 0:
    fig = px.bar(df_balance, x='名前', y='借金残高', title=f"{lender} への借金状況", 
                 color='借金残高', color_continuous_scale="Reds")
    st.plotly_chart(fig, use_container_width=True)

# --- 取引入力エリア ---
st.markdown("---")
st.subheader("📝 取引を入力")

tab1, tab2, tab3 = st.tabs(["💸 借金・割り勘", "↩️ 返済", "🔀 友達間の移動"])

with tab1:
    with st.form("borrow_form", clear_on_submit=True):
        target_users = st.multiselect("対象者", st.session_state.users, default=st.session_state.users)
        amount_total = st.number_input("金額", min_value=0, step=100)
        split_method = st.radio("入力方法", ["全員にこの金額を追加", "合計金額を全員で割る"])
        desc_borrow = st.text_input("内容", "割り勘")
        if st.form_submit_button("登録"):
            if target_users and amount_total > 0:
                amount_per = int(amount_total / len(target_users)) if split_method == "合計金額を全員で割る" else amount_total
                
                for user in target_users:
                    record = {
                        '日時': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'タイプ': '借入', '対象者': user, '金額': amount_per, 'メモ': desc_borrow
                    }
                    save_record(record)
                st.success("登録しました！")
                st.rerun()

with tab2:
    with st.form("repay_form", clear_on_submit=True):
        payer = st.selectbox("返済する人", st.session_state.users)
        amount_repay = st.number_input("返済額", min_value=0, step=100)
        desc_repay = st.text_input("メモ", "現金返済")
        if st.form_submit_button("返済を記録"):
            if amount_repay > 0:
                record = {
                    '日時': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'タイプ': '返済', '対象者': payer, '金額': -amount_repay, 'メモ': desc_repay
                }
                save_record(record)
                st.success("返済を記録しました！")
                st.rerun()

with tab3:
    with st.form("transfer_form", clear_on_submit=True):
        taker = st.selectbox("お金を渡した人 (借金増)", st.session_state.users)
        reducer = st.selectbox("お金をもらった人 (借金減)", st.session_state.users)
        amt = st.number_input("移動金額", min_value=0, step=100)
        reason = st.text_input("移動の理由", placeholder="ランチ代の立て替え、など")
        
        if st.form_submit_button("数値移動を実行"):
            if amt > 0 and taker != reducer:
                memo_taker = f"{reducer}への支払い" + (f" ({reason})" if reason else "")
                memo_reducer = f"{taker}からの受取" + (f" ({reason})" if reason else "")
                
                rec1 = {'日時': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'タイプ': '移動(+)', '対象者': taker, '金額': amt, 'メモ': memo_taker}
                rec2 = {'日時': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'タイプ': '移動(-)', '対象者': reducer, '金額': -amt, 'メモ': memo_reducer}
                
                save_record(rec1)
                save_record(rec2)
                st.success("移動を記録しました！")
                st.rerun()

# --- 履歴表示（取引後残高付き） ---
st.markdown("---")
st.subheader("📜 取引履歴 (最新順)")
history_df = get_history_with_balance(df_trans)

if not history_df.empty:
    history_df = history_df[['日時', '対象者', 'タイプ', '金額', '取引後残高', 'メモ']]
    st.dataframe(history_df, use_container_width=True)
else:
    st.write("履歴はまだありません。")
