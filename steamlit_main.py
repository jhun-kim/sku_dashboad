import streamlit as st
import pandas as pd
from collections import deque
from datetime import datetime
from io import BytesIO
import os

# --- 1. 페이지 설정 및 스타일 ---
st.set_page_config(layout="wide", page_title="AI Tracking System")
st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 320px; max-width: 320px; }
    .stMetric { background-color: #f0f2f6; padding: 15px; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)


# --- 2. 초기 상태 설정 및 데이터 로드 ---
def initialize_state():
    if 'history' not in st.session_state:
        file_path = 'inventory_10k_data.xlsx'
        if os.path.exists(file_path):
            df = pd.read_excel(file_path)
            df['날짜'] = pd.to_datetime(df['날짜'])
            st.session_state.history = df.sort_values(by='날짜').reset_index(drop=True)
        else:
            st.session_state.history = pd.DataFrame(columns=['날짜', '품목명', '구분', '수량', '단가', '매출원가', '비고'])

    if 'inventory_queues' not in st.session_state:
        reconstruct_queues()

    if 'latest_fifo_detail' not in st.session_state:
        st.session_state.latest_fifo_detail = pd.DataFrame()


def reconstruct_queues():
    """전체 히스토리를 순회하여 현재 시점의 품목별 FIFO 큐(재고 층)를 복원"""
    items = st.session_state.history['품목명'].unique()
    queues = {item: deque() for item in items}
    for _, row in st.session_state.history.iterrows():
        item = row['품목명']
        if row['구분'] == '입고':
            queues[item].append({'date': row['날짜'], 'qty': row['수량'], 'price': row['단가']})
        elif row['구분'] == '출고':
            qty = row['수량']
            while qty > 0 and queues.get(item):
                if queues[item][0]['qty'] <= qty:
                    qty -= queues[item][0]['qty']
                    queues[item].popleft()
                else:
                    queues[item][0]['qty'] -= qty
                    qty = 0
    st.session_state.inventory_queues = queues


# --- 3. 핵심 비즈니스 로직: FIFO 엔진 ---
def process_transaction(date, item, action, qty, price=0):
    date = pd.to_datetime(date)
    new_record = {
        '날짜': date, '품목명': item, '구분': action,
        '수량': qty, '단가': price if action == '입고' else 0,
        '매출원가': 0, '비고': ''
    }

    if item not in st.session_state.inventory_queues:
        st.session_state.inventory_queues[item] = deque()

    if action == "입고":
        st.session_state.inventory_queues[item].append({'date': date, 'qty': qty, 'price': price})
        new_record['비고'] = f"{qty}개 입고 완료"
        # 입고 시에는 분석 상세 내역 초기화
        st.session_state.latest_fifo_detail = pd.DataFrame()
        st.session_state.latest_batch_status = pd.DataFrame()

    elif action == "출고":
        remaining_needed = qty
        total_cogs = 0
        fifo_breakdown = []  # 차감 내역
        batch_status = []  # 차감 후 잔량 현황

        queue = st.session_state.inventory_queues[item]

        while remaining_needed > 0 and queue:
            batch = queue[0]
            batch_date_str = batch['date'].strftime('%Y-%m-%d')

            if batch['qty'] <= remaining_needed:
                # 1. 배치 완전 소진
                use_qty = batch['qty']
                cost = use_qty * batch['price']
                total_cogs += cost
                remaining_needed -= use_qty

                # 차감 내역 저장
                fifo_breakdown.append({'입고날짜': batch_date_str, '차감수량': use_qty, '단가': batch['price'], '금액': cost})

                # 차감 후 잔량 저장 (0개)
                batch_status.append({'입고날짜': batch_date_str, '품목명': item, '재고수량': 0, '단가': batch['price'], '금액': 0})

                queue.popleft()  # 큐에서 제거
            else:
                # 2. 배치 부분 소진
                use_qty = remaining_needed
                cost = use_qty * batch['price']
                total_cogs += cost
                batch['qty'] -= use_qty  # 잔량 업데이트
                remaining_needed = 0

                # 차감 내역 저장
                fifo_breakdown.append({'입고날짜': batch_date_str, '차감수량': use_qty, '단가': batch['price'], '금액': cost})

                # 차감 후 잔량 저장 (남은 수량)
                rem_qty = batch['qty']
                batch_status.append({'입고날짜': batch_date_str, '품목명': item, '재고수량': rem_qty, '단가': batch['price'],
                                     '금액': rem_qty * batch['price']})

        new_record['매출원가'] = total_cogs
        new_record['비고'] = "출고 완료" if remaining_needed == 0 else "재고 부족 발생"

        # 세션 상태 업데이트
        st.session_state.latest_fifo_detail = pd.DataFrame(fifo_breakdown)
        st.session_state.latest_batch_status = pd.DataFrame(batch_status)

    # 히스토리 반영
    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_record])], ignore_index=True)
    st.session_state.history = st.session_state.history.sort_values(by='날짜').reset_index(drop=True)

# --- 4. 메인 UI 구성 ---
initialize_state()

# [사이드바 영역]
with st.sidebar:
    st.title("⚙️ 시스템 메뉴")
    app_mode = st.radio("작업 모드 선택", ["실시간 FIFO 관리", "데이터 분석/트래킹"])
    st.divider()

    # [사이드바 실시간 재고 현황]
    st.subheader("📦 품목별 현재고 현황")
    stock_data = []
    # 모든 품목을 순회하며 큐에 남은 수량 합산
    for item, queue in st.session_state.inventory_queues.items():
        total_q = sum(b['qty'] for b in queue)
        stock_data.append({"품목명": item, "현재고": total_q})

    if stock_data:
        st.dataframe(pd.DataFrame(stock_data).sort_values('품목명'), hide_index=True, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")

    if st.button("💾 최종 상태 엑셀 저장", use_container_width=True):
        st.session_state.history.to_excel('inventory_10k_data.xlsx', index=False)
        st.success("엑셀 파일이 업데이트되었습니다.")

# --- 5. 모드별 화면 출력 ---

if app_mode == "실시간 FIFO 관리":
    st.title("📥 입출고 관리")

    # 입력창
    with st.expander("📝 입출고 기록 입력", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        with c1:
            t_date = st.date_input("날짜", datetime.now())
        with c2:
            item_list = sorted(st.session_state.history['품목명'].unique()) if not st.session_state.history.empty else [
                "품목A"]
            t_item = st.selectbox("품목명", item_list)
        with c3:
            t_qty = st.number_input("수량", min_value=1, value=10)
        with c4:
            t_price = st.number_input("입고단가", min_value=0, value=1000)

        btn_in, btn_out = st.columns(2)
        if btn_in.button("📥 입고 실행", use_container_width=True):
            process_transaction(t_date, t_item, "입고", t_qty, t_price)
            st.rerun()
        if btn_out.button("📤 출고 실행", use_container_width=True, type="primary"):
            process_transaction(t_date, t_item, "출고", t_qty)
            st.rerun()

    st.divider()

    # 하단 3분할 레이아웃
    col_left, col_mid, col_right = st.columns([1.2, 1, 0.8])

    with col_left:
        st.subheader("📋 전체 이력")
        # 현재 선택한 품목의 실시간 재고를 Metric으로 표시
        curr_stock = sum(b['qty'] for b in st.session_state.inventory_queues.get(t_item, []))
        st.metric(f"{t_item} 실시간 재고", f"{curr_stock:,} 개")
        st.dataframe(st.session_state.history, use_container_width=True, height=450)

    with col_mid:
        st.subheader("🕒 최근 거래")

        # 1. 세션 상태에서 데이터를 복사
        # if 'history' in st.session_state:
        up_df = st.session_state.history.copy()

        # 2. 날짜 기준 내림차순 정렬 (최신 날짜가 위로)
        # 오타 수정: sort_value -> sort_values
        up_df = up_df.sort_values('날짜', ascending=False)

        # 3. 데이터프레임 출력
        # 'up_df.history'가 아니라 이미 복사본인 'up_df'를 사용해야 합니다.
        # tail(10)은 마지막 10개, 최신 10개를 보려면 정렬 후 head(10)을 쓰기도 합니다.
        st.dataframe(up_df.head(10))
        # else:
        #     st.sidebar.write("기록이 없습니다.")

    with col_right:
        st.subheader("🧪 FIFO 원가 분석 (방금 출고분)")

        if not st.session_state.latest_fifo_detail.empty:
            st.write("▼ 이번 거래로 차감된 상세 내역")
            st.table(st.session_state.latest_fifo_detail)

            total_sum = st.session_state.latest_fifo_detail['금액'].sum()
            st.success(f"**총 매출원가 적용액:** {total_sum:,.0f}원")

            st.divider()  # 시각적 구분선

            # [추가 요청 기능] 차감된 배치의 현재 잔량 현황 표기
            st.write("📅 **관련 입고분 현재 잔량 현황**")
            if 'latest_batch_status' in st.session_state and not st.session_state.latest_batch_status.empty:
                st.dataframe(
                    st.session_state.latest_batch_status,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "재고수량": st.column_config.NumberColumn(format="%d 개"),
                        "단가": st.column_config.NumberColumn(format="%d 원"),
                        "금액": st.column_config.NumberColumn(format="%d 원")
                    }
                )

                # 잔량 금액 합계 수식 예시 (LaTeX)
                total_rem_val = st.session_state.latest_batch_status['금액'].sum()
                st.info(f"위 배치들의 남은 자산 가치 합계: {total_rem_val:,.0f}원")
        else:
            st.info("출고 시 상세 배치 정보가 여기에 표시됩니다.")

elif app_mode == "데이터 분석/트래킹":
    st.title("🔍 수입 적정재고 검토 대시보드")
    st.info("수입 리드 타임을 고려하여 품목별 발주 필요성을 분석합니다. (기준일: 2026-01-14)")

    # 1. 품목 선택 (90여 개의 수입 품목 대응)
    item_list = sorted(st.session_state.history['품목명'].unique())
    if not item_list:
        st.warning("분석할 데이터가 없습니다. 먼저 입고 기록을 생성하세요.")
    else:
        selected_item = st.selectbox("📊 분석할 품목을 선택하세요", item_list)

        # 데이터 계산
        curr_stock, m12_avg, m3_avg = calculate_sales_metrics(selected_item)

        # 2. 핵심 지표 레이아웃 (Metrics)
        st.divider()
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("현재 창고 재고", f"{curr_stock:,} 개")

        with col2:
            st.metric("1년 평균 판매 (월)", f"{int(m12_avg)} 개")

        with col3:
            # 최근 3개월 판매 추세 계산 (전년 평균 대비)
            trend = m3_avg - m12_avg
            st.metric("최근 3개월 판매 (월)", f"{int(m3_avg)} 개", delta=f"{trend:,.1f} (추세)")

        with col4:
            # 재고 보유 개월 수 (현재고 / 최근 3개월 판매량)
            stock_months = curr_stock / m3_avg if m3_avg > 0 else 0
            st.metric("재고 소진 예정 (개월)", f"{stock_months:.1f} 개월분")

        # 3. 발주 제언 시각화
        st.subheader("💡 AI 발주 판단 가이드")

        # 간단한 로직 예시: 재고가 3개월 판매량보다 적으면 발주 검토
        lead_time_buffer = 2.0  # 수입 리드타임 2개월 가정
        if stock_months < lead_time_buffer:
            st.error(f"⚠️ **발주 검토 필요**: 현재 재고가 리드타임({lead_time_buffer}개월) 대비 부족합니다.")
        elif stock_months < lead_time_buffer + 1:
            st.warning("🟡 **관찰 필요**: 재고 수준이 적정선 하단에 도달했습니다.")
        else:
            st.success("✅ **재고 충분**: 현재 안정적인 재고 수준을 유지하고 있습니다.")

        # 4. 상세 판매 차트 (Optional)
        st.subheader("📈 월별 출고 트렌드")
        item_history = st.session_state.history[
            (st.session_state.history['품목명'] == selected_item) &
            (st.session_state.history['구분'] == '출고')
            ].set_index('날짜')

        if not item_history.empty:
            # 월별로 리샘플링하여 합계 계산
            monthly_sales = item_history['수량'].resample('ME').sum()
            monthly_growth = monthly_sales.pct_change() * 100
            st.metric("전월 대비 성장률", f"{monthly_sales.iloc[-1]:,.0f} 개", delta=f"{monthly_growth.iloc[-2]:.1f}%")
            st.bar_chart(monthly_sales)
        else:
            st.write("판매 기록이 없어 차트를 표시할 수 없습니다.")