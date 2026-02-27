import streamlit as st
import pandas as pd
from collections import deque
from datetime import datetime
import hashlib  # 중복 방지용 해시 생성
import os

# --- 1. 페이지 설정 및 스타일 ---
st.set_page_config(layout="wide", page_title="AI Tracking System 2026")
st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 320px; }
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; }
    </style>
    """, unsafe_allow_html=True)


# --- 2. 핵심 유틸리티 함수 ---

def generate_row_hash(row):
    """데이터 행의 고유 해시값 생성 (날짜, 품목명, 구분, 수량, 단가 기준)"""
    payload = f"{row['날짜']}{row['품목명']}{row['구분']}{row['수량']}{row['단가']}"
    return hashlib.md5(payload.encode()).hexdigest()


def initialize_state():
    """세션 상태 초기화 및 데이터 로드"""
    if 'history' not in st.session_state:
        file_path = 'inventory_10k_data.xlsx'
        if os.path.exists(file_path):
            df = pd.read_excel(file_path)
            df['날짜'] = pd.to_datetime(df['날짜'])
            # 기존 데이터에 세부구분 컬럼이 없을 경우 기본값 할당
            if '세부구분' not in df.columns:
                df['세부구분'] = df['구분'].map({'입고': '매입', '출고': '매출'})
            if 'hash' not in df.columns:
                df['hash'] = df.apply(generate_row_hash, axis=1)
            st.session_state.history = df.sort_values(by='날짜').reset_index(drop=True)
        else:
            st.session_state.history = pd.DataFrame(columns=['날짜', '품목명', '구분', '세부구분', '수량', '단가', '매출원가', '비고', 'hash'])

    if 'inventory_queues' not in st.session_state:
        reconstruct_queues()
    if 'latest_fifo_detail' not in st.session_state:
        st.session_state.latest_fifo_detail = pd.DataFrame()


def reconstruct_queues():
    """전체 히스토리를 순회하여 FIFO 큐 복원"""
    items = st.session_state.history['품목명'].unique()
    queues = {item: deque() for item in items}
    # 날짜 순서대로 다시 계산하여 무결성 보장
    sorted_hist = st.session_state.history.sort_values('날짜')
    for _, row in sorted_hist.iterrows():
        item = row['품목명']
        if row['구분'] == '입고':
            queues[item].append({'date': row['날짜'], 'qty': row['수량'], 'price': row['단가']})
        elif row['구분'] == '출고':
            qty = row['수량']
            q = queues.get(item, deque())
            while qty > 0 and q:
                if q[0]['qty'] <= qty:
                    qty -= q[0]['qty']
                    q.popleft()
                else:
                    q[0]['qty'] -= qty
                    qty = 0
    st.session_state.inventory_queues = queues


# --- 3. 비즈니스 로직 ---

# --- [핵심 로직] FIFO 엔진 및 비고 기록 기능 ---
def process_transaction(date, item, action, sub_type, qty, price=0, row_hash=None):
    """
    단일 트랜잭션을 처리하며, 출고 시 어떤 배치의 재고가 사용되었는지 비고에 기록함
    """
    date = pd.to_datetime(date)
    if not row_hash:
        row_hash = hashlib.md5(f"{date}{item}{action}{sub_type}{qty}{price}".encode()).hexdigest()

    new_record = {
        '날짜': date, '품목명': item, '구분': action, '세부구분': sub_type,
        '수량': qty, '단가': price if action == '입고' else 0,
        '매출원가': 0, '비고': '', 'hash': row_hash
    }

    if item not in st.session_state.inventory_queues:
        st.session_state.inventory_queues[item] = deque()
    queue = st.session_state.inventory_queues[item]

    if action == "입고":
        queue.append({'date': date, 'qty': qty, 'price': price})
        new_record['비고'] = f"[{sub_type}] {qty}개 입고 완료"

    elif action == "출고":
        remaining = qty
        total_cogs = 0
        details = []  # 비고 작성을 위한 상세 내역 리스트

        while remaining > 0 and queue:
            batch = queue[0]
            batch_date_str = batch['date'].strftime('%Y-%m-%d')

            if batch['qty'] <= remaining:
                # 배치 완전 소진
                use_qty = batch['qty']
                cost = use_qty * batch['price']
                total_cogs += cost
                remaining -= use_qty
                details.append(f"{batch_date_str}분 {use_qty}개(@{batch['price']:,}원)")
                queue.popleft()
            else:
                # 배치 부분 소진
                use_qty = remaining
                cost = use_qty * batch['price']
                total_cogs += cost
                batch['qty'] -= use_qty
                remaining = 0
                details.append(f"{batch_date_str}분 {use_qty}개(@{batch['price']:,}원)")

        new_record['매출원가'] = total_cogs

        # --- [수정 포인트] 비고란에 상세 출고 내역 작성 ---
        if remaining == 0:
            detail_str = ", ".join(details)
            new_record['비고'] = f"[{sub_type}] 출고완료 ({detail_str})"
        else:
            detail_str = ", ".join(details) if details else "재고 없음"
            new_record['비고'] = f"⚠️재고부족 (일부출고: {detail_str}, 미출고: {remaining}개)"

    # 히스토리에 기록 추가
    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_record])], ignore_index=True)


# --- 4. 엑셀 업로드 처리 ---

def handle_excel_upload(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        required = ['날짜', '품목명', '구분', '세부구분', '수량', '단가']
        if not all(c in df.columns for c in required):
            st.error(f"양식 오류! 필수 컬럼: {required}")
            return

        df['날짜'] = pd.to_datetime(df['날짜'])
        df['hash'] = df.apply(generate_row_hash, axis=1)

        existing_hashes = set(st.session_state.history['hash'].tolist())
        new_data = df[~df['hash'].isin(existing_hashes)].copy()

        if new_data.empty:
            st.warning("추가할 신규 데이터가 없습니다.")
            return

        new_data = new_data.sort_values('날짜')
        with st.status("데이터 분석 중...") as status:
            for _, row in new_data.iterrows():
                process_transaction(row['날짜'], row['품목명'], row['구분'], row['세부구분'], row['수량'], row['단가'], row['hash'])
            status.update(label="반영 완료!", state="complete")

        st.session_state.history = st.session_state.history.sort_values('날짜').reset_index(drop=True)
        st.rerun()
    except Exception as e:
        st.error(f"파일 처리 오류: {e}")

# --- [추가] 3-1. 판매 지표 계산 로직 ---
def calculate_sales_metrics(item_name):
    """
    특정 품목의 1년 평균 및 최근 3개월 평균 판매량을 계산
    """
    history = st.session_state.history
    now = datetime.now()

    # 해당 품목의 '출고' 기록만 필터링
    sales_df = history[(history['품목명'] == item_name) & (history['구분'] == '출고')].copy()

    if sales_df.empty:
        return 0, 0, 0

    # 날짜 필터링을 위한 기준 설정
    one_year_ago = now - pd.Timedelta(days=365)
    three_months_ago = now - pd.Timedelta(days=90)

    # 1. 1년 기준 월평균 판매량 (최근 365일 판매량 / 12)
    last_year_sales = sales_df[sales_df['날짜'] >= one_year_ago]['수량'].sum()
    avg_12m = last_year_sales / 12

    # 2. 최근 3개월 월평균 판매량 (최근 90일 판매량 / 3)
    last_3m_sales = sales_df[sales_df['날짜'] >= three_months_ago]['수량'].sum()
    avg_3m = last_3m_sales / 3

    # 3. 현재고
    current_stock = sum(b['qty'] for b in st.session_state.inventory_queues.get(item_name, []))

    return current_stock, avg_12m, avg_3m


# --- [추가] 3-2. 실시간 재고 집계 함수 ---
def get_inventory_summary():
    """현재 FIFO 큐에 남은 데이터를 기반으로 품목별 요약 생성"""
    summary_data = []

    for item, queue in st.session_state.inventory_queues.items():
        total_qty = sum(batch['qty'] for batch in queue)
        total_value = sum(batch['qty'] * batch['price'] for batch in queue)
        avg_price = total_value / total_qty if total_qty > 0 else 0

        if total_qty >= 0:  # 재고가 0인 품목도 포함 (필요시 > 0으로 변경)
            summary_data.append({
                "품목명": item,
                "현재고 수량": total_qty,
                "평균 매입단가": avg_price,
                "재고 자산금액": total_value
            })

    return pd.DataFrame(summary_data)


# --- [추가] 3-3. 차기 출고 예정 재고(FIFO Queue) 분석 함수 ---
def get_next_out_schedule():
    """각 품목별로 FIFO 기준 가장 먼저 출고될 재고 날짜와 수량 분석"""
    schedule_data = []

    for item, queue in st.session_state.inventory_queues.items():
        if not queue:
            continue

        # 1순위 (가장 오래된 재고)
        first_batch = queue[0]

        # 2순위 (있을 경우에만)
        second_batch = queue[1] if len(queue) > 1 else None

        schedule_data.append({
            "품목명": item,
            "1순위 출고예정일": first_batch['date'],
            "1순위 대기수량": first_batch['qty'],
            "1순위 단가": first_batch['price'],
            "2순위 출고예정일": second_batch['date'] if second_batch else None,
            "2순위 대기수량": second_batch['qty'],
            "전체 재고층 수": len(queue)
        })

    return pd.DataFrame(schedule_data)

# --- 4. 메인 UI 구성 ---
initialize_state()

# [사이드바 영역]
with st.sidebar:
    st.title("📦 AI 재고 관리")
    app_mode = st.radio("메뉴 선택", ["데이터 일괄 업로드", "데이터 분석/트래킹"])
    st.divider()
    # 템플릿에도 세부구분 추가
    template = pd.DataFrame(columns=['날짜', '품목명', '구분', '세부구분', '수량', '단가'])
    st.download_button("📥 업로드 양식 다운로드", data=template.to_csv(index=False).encode('utf-8-sig'),
                       file_name="template_v2.csv")

if app_mode == "데이터 일괄 업로드":
    st.title("📥 대량 입출고 업로드 및 이력")

    with st.expander("📁 신규 데이터 업로드"):
        uploaded_file = st.file_uploader("엑셀 파일을 선택하세요", type=['xlsx'])
        if uploaded_file and st.button("🚀 데이터 반영하기", use_container_width=True):
            handle_excel_upload(uploaded_file)

    st.divider()
    st.subheader("🔍 데이터 필터링 (세부구분 포함)")
    df_display = st.session_state.history.copy()

    f1, f2, f3 = st.columns([1.5, 1.5, 2])
    with f1:
        selected_items = st.multiselect("📦 품목 선택", sorted(df_display['품목명'].unique()))
    with f2:
        # 세부구분 필터 추가
        all_subtypes = sorted(df_display['세부구분'].unique())
        selected_subs = st.multiselect("📂 세부구분 선택", all_subtypes, default=all_subtypes)
    with f3:
        if not df_display.empty:
            date_range = st.date_input("📅 기간", value=(df_display['날짜'].min().date(), df_display['날짜'].max().date()))
        else:
            date_range = []

    # 필터 적용
    if selected_items: df_display = df_display[df_display['품목명'].isin(selected_items)]
    df_display = df_display[df_display['세부구분'].isin(selected_subs)]
    if len(date_range) == 2:
        df_display = df_display[
            (df_display['날짜'].dt.date >= date_range[0]) & (df_display['날짜'].dt.date <= date_range[1])]

    st.dataframe(
        df_display.sort_values('날짜', ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "날짜": st.column_config.DatetimeColumn("날짜", format="YYYY-MM-DD"),
            "구분": st.column_config.TextColumn("대분류"),
            "세부구분": st.column_config.TextColumn("입출고 사유"),
            "수량": st.column_config.NumberColumn("수량", format="%d 개"),
            "단가": st.column_config.NumberColumn("단가", format="₩ %d"),
            "매출원가": st.column_config.NumberColumn("원가(FIFO)", format="₩ %d"),
            "hash": None
        }
    )

    # [2] 실시간 재고 요약 섹션 (신규 추가)
    st.subheader("📦 현재고 요약 현황 (품목별)")
    inv_summary_df = get_inventory_summary()


    if not inv_summary_df.empty:
        # 가독성을 위해 3개의 컬럼으로 주요 지표 표시
        tot_items = len(inv_summary_df)
        tot_qty = inv_summary_df['현재고 수량'].sum()
        tot_val = inv_summary_df['재고 자산금액'].sum()

        m1, m2, m3 = st.columns(3)
        m1.metric("관리 품목 수", f"{tot_items} 종")
        m2.metric("전체 재고 수량", f"{tot_qty:,} 개")
        m3.metric("전체 자산 가치", f"₩ {tot_val:,.0f}")

        # 요약 테이블 출력
        st.dataframe(
            inv_summary_df.sort_values("재고 자산금액", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "현재고 수량": st.column_config.NumberColumn(format="%d 개"),
                "평균 매입단가": st.column_config.NumberColumn(format="₩ %d"),
                "재고 자산금액": st.column_config.NumberColumn(format="₩ %d"),
            }
        )
    else:
        st.info("데이터가 없습니다. 엑셀을 업로드해 주세요.")

    st.divider()
    # [신규] 차기 출고 예정 상세 표
    st.subheader("📋 출고 우선순위 현황 (FIFO Queue)")
    st.caption("현재 보유 재고 중 날짜가 가장 오래되어 '다음 출고 시' 가장 먼저 차감될 데이터입니다.")

    next_out_df = get_next_out_schedule()

    if not next_out_df.empty:
        st.dataframe(
            next_out_df.sort_values("1순위 출고예정일"),  # 오래된 순으로 정렬
            use_container_width=True,
            hide_index=True,
            column_config={
                "1순위 출고예정일": st.column_config.DatetimeColumn("가장 오래된 입고일", format="YYYY-MM-DD"),
                "1순위 대기수량": st.column_config.NumberColumn("현 재고(1순위)", format="%d 개"),
                "1순위 단가": st.column_config.NumberColumn("취득단가", format="₩ %d"),
                "2순위 출고예정일": st.column_config.DatetimeColumn("차순위 입고일", format="YYYY-MM-DD"),
                "2순위 대기수량": st.column_config.NumberColumn("차순위 재고(2순위)", format="%d 개"),
                "전체 재고층 수": st.column_config.NumberColumn("누적 입고 횟수", format="%d 층")
            }
        )

    else:
        st.info("출고 대기 중인 재고가 없습니다.")
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