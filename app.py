import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from datetime import datetime
import logging
import warnings
from streamlit_gsheets import GSheetsConnection

# 🚀 터미널 경고 차단
warnings.filterwarnings("ignore", message=".*ScriptRunContext.*")
warnings.filterwarnings("ignore", category=UserWarning)
logging.getLogger("streamlit.runtime.scriptrunner.script_run_context").setLevel(logging.ERROR)
logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)

# ==========================================
# 1. Google Sheets 데이터베이스 연결
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

def get_transactions():
    try:
        df = conn.read(worksheet="Sheet1", ttl=0)
        if df.empty:
            df = pd.DataFrame(columns=['id', 'trade_date', 'trade_type', 'account', 'name', 'asset_class', 'quantity', 'price', 'currency'])
        else:
            df = df.dropna(subset=['trade_date', 'name', 'quantity', 'price'])
        return df
    except Exception as e:
        st.error(f"🚨 구글 시트 연결 실패! 상세 에러 내용: {e}")
        return pd.DataFrame(columns=['id', 'trade_date', 'trade_type', 'account', 'name', 'asset_class', 'quantity', 'price', 'currency'])

def get_korean_name(name_str):
    if "(" in name_str and ")" in name_str:
        return name_str.split("(")[-1].replace(")", "").strip()
    return name_str

@st.cache_data(ttl=86400)
def calculate_historical_cagr(asset_name, asset_class):
    try:
        if "전세" in asset_name or "보증금" in asset_name or asset_class == "부동산": return 0.0
        if "자동차" in asset_name or "GV70" in asset_name or asset_class == "차량/실물": return -0.12
        real_ticker = asset_name.split(" (")[0].strip()
        if "예수금" in real_ticker or "배당금" in real_ticker: return 0.0

        ticker = yf.Ticker(real_ticker)
        hist = ticker.history(period="10y")
        if len(hist) > 10:
            start_price = float(hist['Close'].iloc[0])
            end_price = float(hist['Close'].iloc[-1])
            n_years = (hist.index[-1] - hist.index[0]).days / 365.25
            if n_years > 0:
                cagr = (end_price / start_price) ** (1 / n_years) - 1
                if n_years < 3 or cagr > 0.20 or "AI" in asset_name or "광통신" in asset_name:
                    return 0.10  
                return cagr
        return 0.07
    except:
        return 0.07

@st.cache_data(ttl=86400)
def get_stock_volatility(asset_name, asset_class):
    try:
        if "전세" in asset_name or "보증금" in asset_name or asset_class == "부동산": return 0.00
        if "자동차" in asset_name or "GV70" in asset_name or asset_class == "차량/실물": return 0.05
        real_ticker = asset_name.split(" (")[0].strip()
        if "예수금" in real_ticker or "배당금" in real_ticker: return 0.00

        ticker = yf.Ticker(real_ticker)
        hist = ticker.history(period="1y")
        if len(hist) > 10:
            returns = hist['Close'].pct_change().dropna()
            return returns.std() * (252 ** 0.5)
        return 0.15
    except:
        return 0.15

# ==========================================
# 2. 스트림릿 UI 및 실시간 데이터 연동
# ==========================================
st.set_page_config(page_title="클라우드 자산 관리 대시보드", layout="wide")
st.title("💰 내 모든 자산 한눈에 보기")

@st.cache_data(ttl=3600)
def get_usd_krw_rate():
    try:
        return float(yf.Ticker("USDKRW=X").history(period="1d")["Close"].iloc[-1])
    except:
        return 1350.0

usd_krw = get_usd_krw_rate()

# --- 🧹 사이드바: 입력폼 걷어내고 동기화 버튼만 깔끔하게 배치 ---
st.sidebar.markdown("### 🔄 데이터 동기화")
st.sidebar.caption("구글 시트에 데이터를 입력한 뒤 아래 버튼을 누르면 즉시 반영됩니다.")
if st.sidebar.button("최신 데이터 불러오기", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"💵 현재 적용 환율: 1 USD = {usd_krw:,.2f} 원")
st.sidebar.markdown("[📝 구글 시트 열기 (입력용)](https://docs.google.com/spreadsheets/d/12C3FJtLs5Wn3JGVW6ZcUj_M6-iHc8TlL0KPUA6iOYCs/edit)")

df_tx = get_transactions()

# ==========================================
# 3. 데이터 연산 및 렌더링 파이프라인
# ==========================================
if not df_tx.empty:
    portfolio_data = []
    grouped = df_tx.groupby(['account', 'name', 'asset_class', 'currency'])
    
    for (acc, nm, cls, curr), group in grouped:
        running_qty, running_cost = 0.0, 0.0
        
        for _, row in group.iterrows():
            qty, prc = float(row['quantity']), float(row['price'])
            if row['trade_type'] == '매수':
                running_qty += qty
                running_cost += (qty * prc)
            elif row['trade_type'] == '매도':
                if running_qty > 0:
                    running_cost -= (qty * (running_cost / running_qty))
                running_qty -= qty
            elif row['trade_type'] == '단가 보정':
                running_cost += prc
                
        if running_qty > 0.00001:
            avg_buy_price = running_cost / running_qty if running_qty > 0 else 0
            portfolio_data.append({
                'account': acc, 'name': nm, 'asset_class': cls, 'currency': curr,
                'quantity': running_qty, 'buy_price': avg_buy_price, 'total_invested': running_cost
            })

    df_portfolio = pd.DataFrame(portfolio_data)
    
    if not df_portfolio.empty:
        current_prices, eval_values_manwon, buy_values_manwon = [], [], []
        day_changes, day_change_pcts = [], []

        for idx, row in df_portfolio.iterrows():
            cur_price = float(row['buy_price'])
            day_change = 0.0
            day_change_pct = 0.0
            
            if row['asset_class'] == "주식/ETF":
                try:
                    real_ticker = row['name'].split(" (")[0].strip()
                    hist = yf.Ticker(real_ticker).history(period="2d")
                    if len(hist) >= 2:
                        cur_price = float(hist["Close"].iloc[-1])
                        prev_price = float(hist["Close"].iloc[-2])
                        day_change = cur_price - prev_price
                        day_change_pct = (day_change / prev_price) * 100
                    elif not hist.empty:
                        cur_price = float(hist["Close"].iloc[-1])
                except:
                    pass
            
            current_prices.append(cur_price)
            day_changes.append(day_change)
            day_change_pcts.append(day_change_pct)
            
            rate = usd_krw if row['currency'] == "USD" else 1
            buy_values_manwon.append((row['total_invested'] * rate) / 10000)
            eval_values_manwon.append((cur_price * row['quantity'] * rate) / 10000)

        df_portfolio['현재가'] = current_prices
        df_portfolio['당일변동폭'] = day_changes
        df_portfolio['당일등락률'] = day_change_pcts
        df_portfolio['총매입금액(만원)'] = buy_values_manwon
        df_portfolio['평가금액(만원)'] = eval_values_manwon
        df_portfolio['수익률(%)'] = ((df_portfolio['현재가'] - df_portfolio['buy_price']) / df_portfolio['buy_price']) * 100
        
        total_eval_manwon = sum(eval_values_manwon)
        total_buy_manwon = sum(buy_values_manwon)
        total_profit_rate = ((total_eval_manwon - total_buy_manwon) / total_buy_manwon * 100) if total_buy_manwon > 0 else 0.0

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 요약 대시보드", "📈 기간별 자산 추이", "🔮 미래 가치 시뮬레이션", "🎯 성과 & 리스크 분석", "📝 매매 기록 확인"
        ])

        with tab1:
            st.markdown("### 🌐 내 총자산 종합")
            col1, col2, col3 = st.columns(3)
            col1.metric("총 자산 평가액", f"{total_eval_manwon:,.0f} 만원")
            col2.metric("현재 투자 원금", f"{total_buy_manwon:,.0f} 만원")
            col3.metric("전체 합산 수익률", f"{total_profit_rate:.2f} %")
            st.markdown("---")

            st.markdown("### 📈 주식/ETF 실시간 잔고 현황 (MTS 뷰)")
            stock_df = df_portfolio[df_portfolio['asset_class'] == "주식/ETF"]
            
            if not stock_df.empty:
                mts_css = """<style>
.mts-container { width: 100%; box-sizing: border-box; }
.mts-account-banner { width: 100%; box-sizing: border-box; background-color: #f1f2f6; padding: 12px 14px; margin-top: 25px; border-radius: 6px 6px 0 0; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #222; font-family: 'Apple SD Gothic Neo', sans-serif;}
.mts-table { width: 100%; box-sizing: border-box; table-layout: fixed; border-collapse: collapse; font-family: 'Apple SD Gothic Neo', sans-serif; background-color: white; margin-bottom: 25px; border-bottom: 1px solid #ccc;}
.mts-table th { border-bottom: 1px solid #eee; padding: 8px 4px; color: #888; font-weight: normal; font-size: 0.75em; text-align: right; background-color: #fafafa;}
.mts-table th:nth-child(1) { text-align: left; width: 33%; }
.mts-table th:nth-child(2) { width: 23%; }
.mts-table th:nth-child(3) { width: 22%; }
.mts-table th:nth-child(4) { width: 22%; }
.mts-row { border-bottom: 1px solid #eee; }
.mts-cell { padding: 10px 4px; text-align: right; line-height: 1.3; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.mts-cell:first-child { text-align: left; }
.top-text { font-size: 0.88em; font-weight: 600; color: #222; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.sub-text { font-size: 0.75em; color: #777; margin-top: 3px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.val-blue { color: #0984e3 !important; }
.val-red { color: #d63031 !important; }

@media screen and (max-width: 600px) {
    .mts-table th { font-size: 0.65em; padding: 6px 2px; }
    .mts-cell { padding: 8px 2px; }
    .top-text { font-size: 0.75em; }
    .sub-text { font-size: 0.62em; }
    .mts-account-banner { flex-direction: column; align-items: flex-start; gap: 4px; padding: 10px; }
    .mts-account-banner > div:last-child { align-self: flex-start; text-align: left !important; }
}
</style>"""
                
                html_content = mts_css + '<div class="mts-container">'
                
                for acc, acc_group in stock_df.groupby('account'):
                    acc_eval_manwon = acc_group['평가금액(만원)'].sum()
                    acc_buy_manwon = acc_group['총매입금액(만원)'].sum()
                    acc_profit_manwon = acc_eval_manwon - acc_buy_manwon
                    acc_return_pct = (acc_profit_manwon / acc_buy_manwon * 100) if acc_buy_manwon > 0 else 0.0
                    
                    acc_color = "val-red" if acc_profit_manwon > 0 else "val-blue" if acc_profit_manwon < 0 else ""
                    acc_sign = "+" if acc_profit_manwon > 0 else ""
                    
                    html_content += f"""<div class="mts-account-banner">
<div style="font-weight: bold; color: #2f3542; font-size: 1.0em; text-align: left;">📍 {acc}</div>
<div style="font-size: 0.85em; color: #57606f; text-align: right;">총 평가: <b>{acc_eval_manwon:,.0f} 만원</b> (<span class="{acc_color}">{acc_sign}{acc_return_pct:.2f}%</span>)</div>
</div>"""
                    
                    html_content += """<table class="mts-table">
<thead>
<tr>
<th>종목명<br><span style="font-size:0.8em; color:#aaa;">보유수량</span></th>
<th>평가손익<br><span style="font-size:0.8em; color:#aaa;">수익률(%)</span></th>
<th>평가금액<br><span style="font-size:0.8em; color:#aaa;">매입금액</span></th>
<th>현재가<br><span style="font-size:0.8em; color:#aaa;">오늘 변동(%)</span></th>
</tr>
</thead>
<tbody>"""
                    
                    for idx, row in acc_group.iterrows():
                        korean_name = get_korean_name(row['name'])
                        qty = row['quantity']
                        eval_amt = row['평가금액(만원)'] * 10000
                        buy_amt = row['총매입금액(만원)'] * 10000
                        profit_loss = eval_amt - buy_amt
                        return_pct = row['수익률(%)']
                        
                        cur_price = row['현재가']
                        day_change = row['당일변동폭']
                        day_pct = row['당일등락률']
                        
                        is_usd = row['currency'] == "USD"
                        price_fmt = "{:,.2f}" if is_usd else "{:,.0f}"
                        
                        color_class = "val-red" if profit_loss > 0 else "val-blue" if profit_loss < 0 else ""
                        sign = "+" if profit_loss > 0 else ""
                        
                        day_color = "val-red" if day_change > 0 else "val-blue" if day_change < 0 else ""
                        day_sign = "▲" if day_change > 0 else "▼" if day_change < 0 else ""
                        day_display = f"{day_sign}{abs(day_change):,.0f} ({day_pct:+.2f}%)" if day_change != 0 else "0.00 (0.00%)"
                        if is_usd and day_change != 0:
                            day_display = f"{day_sign}{abs(day_change):,.2f} ({day_pct:+.2f}%)"
                        
                        html_content += f"""<tr class="mts-row">
<td class="mts-cell" title="{korean_name}"><div class="top-text">{korean_name}</div><div class="sub-text">{qty:,.2f}</div></td>
<td class="mts-cell"><div class="top-text {color_class}">{sign}{profit_loss:,.0f}</div><div class="sub-text {color_class}">{sign}{return_pct:,.2f}%</div></td>
<td class="mts-cell"><div class="top-text">{eval_amt:,.0f}</div><div class="sub-text">{buy_amt:,.0f}</div></td>
<td class="mts-cell"><div class="top-text">{price_fmt.format(cur_price)}</div><div class="sub-text {day_color}">{day_display}</div></td>
</tr>"""
                    
                    html_content += "</tbody></table>"
                
                html_content += '</div>'
                st.markdown(html_content, unsafe_allow_html=True)
            else:
                st.info("현재 잔고에 주식/ETF 자산이 없습니다.")
                
            st.markdown("---")

            st.markdown("### 🏦 내 계좌별 자산 현황")
            accounts = df_portfolio['account'].unique()
            acc_cols = st.columns(4) 
            for i, acc in enumerate(accounts):
                acc_df = df_portfolio[df_portfolio['account'] == acc]
                acc_eval = acc_df['평가금액(만원)'].sum()
                acc_buy = acc_df['총매입금액(만원)'].sum()
                acc_profit = ((acc_eval - acc_buy) / acc_buy * 100) if acc_buy > 0 else 0.0
                with acc_cols[i % 4]:
                    st.metric(f"📍 {acc}", f"{acc_eval:,.0f} 만원", f"{acc_profit:.2f}%")
            
            st.markdown("---")
            st.subheader("📊 현재 포트폴리오 비중")
            exclude_real_estate = st.checkbox("🏠 부동산(전세금) 및 실물 자산 숨기기", value=False)
            if exclude_real_estate:
                non_financial = ["주택전세금", "자가", "상가/오피스텔", "토지", "자동차", "이륜차", "귀금속", "기타 실물자산"]
                chart_df = df_portfolio[~df_portfolio['account'].isin(non_financial)]
            else:
                chart_df = df_portfolio

            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig_tree = px.treemap(chart_df, path=[px.Constant("내 자산"), 'account', 'name'], values='평가금액(만원)')
                fig_tree.update_traces(textinfo="label+value", texttemplate="%{label}<br>%{value:,.0f} 만원")
                st.plotly_chart(fig_tree, use_container_width=True)
            with chart_col2:
                fig_donut = px.pie(chart_df, values='평가금액(만원)', names='asset_class', hole=0.4)
                st.plotly_chart(fig_donut, use_container_width=True)

        with tab2:
            st.subheader("📈 시간 흐름에 따른 투자 자산 증가율 추이")
            exclude_real_timeline = st.checkbox("🏠 그래프에서 부동산 및 차량/실물 제외", value=False)
            df_tx_line = df_tx.copy()
            
            if exclude_real_timeline:
                non_financial_classes = ["부동산", "차량/실물"]
                df_tx_line = df_tx_line[~df_tx_line['asset_class'].isin(non_financial_classes)]
                df_tx_line = df_tx_line[~df_tx_line['account'].str.contains("전세|자가|자동차|차량|오피스텔", na=False)]
                df_tx_line = df_tx_line[~df_tx_line['name'].str.contains("전세|GV70|자동차", na=False)]
            
            if not df_tx_line.empty:
                df_tx_line['net_invested'] = df_tx_line.apply(
                    lambda x: (float(x['quantity']) * float(x['price']) * (usd_krw if x['currency'] == 'USD' else 1)) if x['trade_type'] == '매수'
                    else (-(float(x['quantity']) * float(x['price']) * (usd_krw if x['currency'] == 'USD' else 1)) if x['trade_type'] == '매도'
                    else float(x['price']) * (usd_krw if x['currency'] == 'USD' else 1)), axis=1
                )
                df_timeline = df_tx_line.groupby('trade_date')['net_invested'].sum().reset_index()
                df_timeline['누적투자금액(만원)'] = df_timeline['net_invested'].cumsum() / 10000
                
                first_val = df_timeline['누적투자금액(만원)'].iloc[0] if not df_timeline.empty else 1
                df_timeline['자산증가율(%)'] = ((df_timeline['누적투자금액(만원)'] - first_val) / (first_val if first_val != 0 else 1)) * 100
                
                graph_type = st.radio("그래프 표시 기준 선택", ["누적 자산 규모 추이 (만원)", "첫 거래 대비 자산 증가율 (%)"], horizontal=True)
                
                if graph_type == "누적 자산 규모 추이 (만원)":
                    fig_timeline = px.line(df_timeline, x='trade_date', y='누적투자금액(만원)', markers=True)
                    fig_timeline.update_layout(yaxis=dict(tickformat=","))
                else:
                    fig_timeline = px.line(df_timeline, x='trade_date', y='자산증가율(%)', markers=True)
                st.plotly_chart(fig_timeline, use_container_width=True)

        with tab3:
            st.subheader("🔮 자산별 미래 가치 시뮬레이션 (적립식 추가 납입 연동)")
            predict_years = st.slider("미래 예측 기간 선택 (년 후)", min_value=1, max_value=30, value=10, key="future_slider")
            
            sim_basis = []
            for idx, row in df_portfolio.iterrows():
                cagr = calculate_historical_cagr(row['name'], row['asset_class'])
                
                annual_add_manwon = 0.0
                if "ISA" in row['account'] or "연금" in row['account']:
                    df_hist = df_tx[(df_tx['account'] == row['account']) & (df_tx['name'] == row['name']) & (df_tx['trade_type'] == '매수')].copy()
                    if not df_hist.empty:
                        df_hist['trade_date'] = pd.to_datetime(df_hist['trade_date'])
                        min_date = df_hist['trade_date'].min()
                        max_date = datetime.today()
                        years_active = max(1.0, (max_date - min_date).days / 365.25)
                        
                        df_hist['invest_krw'] = df_hist.apply(lambda x: float(x['quantity']) * float(x['price']) * (usd_krw if x['currency'] == 'USD' else 1), axis=1)
                        total_hist_invested = df_hist['invest_krw'].sum()
                        annual_add_manwon = (total_hist_invested / years_active) / 10000

                sim_basis.append({
                    'account': row['account'], 'name': row['name'], 'cagr': cagr,
                    'current_val_manwon': row['평가금액(만원)'], 'annual_add_manwon': annual_add_manwon, 'running_val': row['평가금액(만원)']
                })
            
            sim_timeline = []
            for y in range(0, predict_years + 1):
                for row_dict in sim_basis:
                    if y == 0:
                        future_val_manwon = row_dict['current_val_manwon']
                    else:
                        row_dict['running_val'] = (row_dict['running_val'] + row_dict['annual_add_manwon']) * (1 + row_dict['cagr'])
                        future_val_manwon = row_dict['running_val']
                        
                    sim_timeline.append({
                        '연도': f"{y}년 후", '자산명': row_dict['name'], '계좌': row_dict['account'],
                        '연 성장률': f"{row_dict['cagr']*100:.2f}%", '예측 평가액(억)': max(0.0, future_val_manwon) / 10000
                    })
            
            df_sim_result = pd.DataFrame(sim_timeline)
            
            fig_sim = px.bar(df_sim_result, x='연도', y='예측 평가액(억)', color='자산명', title=f"향후 {predict_years}년간 자산 복리 성장 (단위: 억)")
            fig_sim.update_layout(yaxis=dict(tickformat=".2f"))
            st.plotly_chart(fig_sim, use_container_width=True)
            
            st.markdown("#### 📋 연도별 자산 가치 상세 예측 표")
            df_pivot = df_sim_result.pivot_table(index=['계좌', '자산명', '연 성장률'], columns='연도', values='예측 평가액(억)', aggfunc='sum').reset_index()
            ordered_cols = ['계좌', '자산명', '연 성장률'] + [f"{y}년 후" for y in range(0, predict_years + 1)]
            df_pivot = df_pivot[ordered_cols]
            st.dataframe(df_pivot.style.format({c: '{:,.2f} 억' for c in ordered_cols if "년 후" in c}), use_container_width=True)

        with tab4:
            st.markdown("## 🎯 고도화 성과 지표 및 리스크 제어 시스템")
            st.markdown("---")
            
            st.markdown("### 📈 알파 트래커 (Alpha Tracker)")
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                init_seed = st.number_input("나의 초기 자본금(시드) 설정 (만원)", min_value=0, value=4400, step=100)
                net_gain = total_eval_manwon - init_seed
                alpha_rate = (net_gain / init_seed * 100) if init_seed > 0 else 0.0
                st.metric("순수 투자 시장 성과 (Alpha)", f"{net_gain:,.0f} 만원", f"{alpha_rate:+.2f}%")
            with col_a2:
                if net_gain > 0:
                    df_alpha = pd.DataFrame({
                        "자산 원천 구분": ["초기 투입 시드 자본", "시장 초과 성장액 (Alpha)"],
                        "금액(만원)": [init_seed, net_gain]
                    })
                    fig_alpha = px.pie(df_alpha, values="금액(만원)", names="자산 원천 구분", hole=0.4, title="내 자산의 성장 원천 비율")
                    st.plotly_chart(fig_alpha, use_container_width=True)
                else:
                    st.info("현재 자산 평가액이 설정된 초기 시드 자본 이하입니다.")

            st.markdown("---")
            
            st.markdown("### 🏁 장기 목표 달성 트래커 (Milestone & Multi-Scenario)")
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                target_amt = st.number_input("장기 자산 달성 목표 설정 (만원)", min_value=0, value=5000, step=500)
                target_yrs = st.number_input("목표 달성 기한 (년)", min_value=1, value=4, step=1)
                add_save_monthly = st.number_input("향후 추가 월 저축 예정액 (결혼 후 공동 저축 등 시나리오, 만원)", min_value=0, value=400, step=10)
            
            future_sim_val = 0.0
            for idx, row in df_portfolio.iterrows():
                cagr = calculate_historical_cagr(row['name'], row['asset_class'])
                asset_val = row['평가금액(만원)']
                for _ in range(target_yrs):
                    asset_val *= (1 + cagr)
                future_sim_val += asset_val
            
            annual_extra_save = add_save_monthly * 12
            accumulated_savings = 0.0
            for _ in range(target_yrs):
                accumulated_savings = (accumulated_savings + annual_extra_save) * 1.04
            
            total_future_milestone = future_sim_val + accumulated_savings
            progress_pct = min(100.0, (total_eval_manwon / target_amt * 100)) if target_amt > 0 else 100.0
            future_progress_pct = min(100.0, (total_future_milestone / target_amt * 100)) if target_amt > 0 else 100.0
            
            with col_m2:
                st.metric("현재 자산 상태 기준 달성률", f"{progress_pct:.1f}%", f"목표: {target_amt/10000:.2f} 억")
                st.progress(progress_pct / 100.0)
                st.metric(f"🔮 {target_yrs}년 뒤 (추가 적립 시나리오 반영) 예상 달성률", f"{future_progress_pct:.1f}%", f"예상 자산 가치: {total_future_milestone/10000:.2f} 억")
                st.progress(future_progress_pct / 100.0)

            st.markdown("---")
            
            st.markdown("### 🛡️ 포트폴리오 변동성 안전지수 및 산포도")
            vols, weights = [], []
            for idx, row in df_portfolio.iterrows():
                vol = get_stock_volatility(row['name'], row['asset_class'])
                vols.append(vol)
                weights.append(row['평가금액(만원)'] / total_eval_manwon)
            
            weighted_vol = sum(w * v for w, v in zip(weights, vols)) * 100
            
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                st.metric("종합 포트폴리오 연환산 변동성 ($\sigma$)", f"{weighted_vol:.2f}%")
                if weighted_vol < 12.0:
                    st.success("📊 **안정형 국면 (Low Volatility)**: 리스크 제어가 완벽히 유지되고 있습니다.")
                elif weighted_vol < 22.0:
                    st.info("📊 **균형형 국면 (Moderate Volatility)**: 균형 잡힌 분산 자산 상태입니다.")
                else:
                    st.warning("📊 **공격형 국면 (High Volatility)**: 자산 재배분을 고려해 볼 만한 국면입니다.")
            with col_v2:
                df_vol_chart = pd.DataFrame({
                    "자산명": [get_korean_name(n) for n in df_portfolio['name']],
                    "연간 변동성(위험도, %)": [v * 100 for v in vols],
                    "포트폴리오 내 비중(%)": [w * 100 for w in weights]
                })
                fig_vol = px.scatter(df_vol_chart, x="연간 변동성(위험도, %)", y="포트폴리오 내 비중(%)", text="자산명", size="포트폴리오 내 비중(%)")
                fig_vol.update_traces(textposition='top center')
                st.plotly_chart(fig_vol, use_container_width=True)

        with tab5:
            st.subheader("📋 구글 시트에 입력된 전체 거래 기록")
            display_tx = df_tx[['id', 'trade_date', 'trade_type', 'account', 'asset_class', 'name', 'quantity', 'price', 'currency']]
            st.dataframe(display_tx.style.format({'quantity': '{:,.2f}', 'price': '{:,.2f}'}), use_container_width=True)
            st.info("데이터 수정 및 삭제는 구글 스프레드시트에서 직접 진행해 주세요.")
else:
    st.info("구글 시트에 등록된 거래 기록이 없습니다. 데이터를 입력해 보세요!")