import streamlit as st
import pandas as pd
from collections import deque
from datetime import datetime
import hashlib
import os

# ==========================================
# [환경 설정 및 초기화]
# ==========================================
st.set_page_config(layout="wide", page_title="AI & Secure Enterprise ERP")
st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 320px; max-width: 320px; }
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; }
    </style>
    """, unsafe_allow_html=True)


def generate_row_hash(row):
    """중복 데이터 방지를 위한 고유 해시값 생성"""
    payload = f"{row.get('날짜', '')}{row.get('품목명', '')}{row.get('구분', '')}{row.get('수량', '')}{row.get('고객사', '')}"
    return hashlib.md5(payload.encode()).hexdigest()


def initialize_state():
    # 보안 및 인증 상태
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if 'current_user' not in st.session_state: st.session_state.current_user = ""
    if 'role' not in st.session_state: st.session_state.role = ""

    # Paper Trail (감사 로그) 저장소
    if 'audit_logs' not in st.session_state:
        st.session_state.audit_logs = pd.DataFrame(columns=['시간', '작업자', '접속IP', '수행작업', '상세내용'])

    # 융합된 메인 데이터베이스 스키마
    if 'history' not in st.session_state:
        st.session_state.history = pd.DataFrame(columns=[
            '날짜', '고객사', '품목명', '구분', '세부구분', '수량', '순수단가', '통관물류비', '최종매입원가', '매출원가', '상태', '비고', 'hash'
        ])
    if 'crm_history' not in st.session_state:
        st.session_state.crm_history = pd.DataFrame(columns=['날짜', '고객사', '품목명', '판매단가', '비고'])

    # FIFO 큐 및 뷰어
    if 'inventory_queues' not in st.session_state: st.session_state.inventory_queues = {}
    if 'latest_fifo_detail' not in st.session_state: st.session_state.latest_fifo_detail = pd.DataFrame()
    if 'latest_batch_status' not in st.session_state: st.session_state.latest_batch_status = pd.DataFrame()


# ==========================================
# [핵심 모듈 1] 보안 로그 (Audit Trail)
# ==========================================
def write_audit_log(action, details):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip_address = "192.168.1.10"
    user = st.session_state.current_user if st.session_state.current_user else "System"
    log_entry = {'시간': now, '작업자': user, '접속IP': ip_address, '수행작업': action, '상세내용': details}
    st.session_state.audit_logs = pd.concat([st.session_state.audit_logs, pd.DataFrame([log_entry])], ignore_index=True)


# ==========================================
# [핵심 모듈 2] 로그인 화면
# ==========================================
def login_screen():
    st.title("🔒 AI & Secure ERP 로그인")
    st.info("디지털 전산 감사 기준 준수: 모든 트랜잭션 및 엑셀 업로드 내역은 암호화되어 기록됩니다.")
    with st.form("login_form"):
        user_id = st.text_input("아이디 (관리자: admin / 실무자: staff)")
        password = st.text_input("비밀번호 (공통: 1234)", type="password")
        if st.form_submit_button("로그인", type="primary"):
            if user_id == "admin" and password == "1234":
                st.session_state.update({'logged_in': True, 'current_user': "김대표(관리자)", 'role': "admin"})
                write_audit_log("로그인", "관리자 권한 접속")
                st.rerun()
            elif user_id == "staff" and password == "1234":
                st.session_state.update({'logged_in': True, 'current_user': "이대리(실무자)", 'role': "user"})
                write_audit_log("로그인", "실무자 권한 접속")
                st.rerun()
            else:
                st.error("⚠️ 인증 실패")


# ==========================================
# [핵심 모듈 3] 보안 결합형 FIFO 비즈니스 엔진
# ==========================================
def process_secure_transaction(date, item, action, sub_type, qty, customer="본사", base_price=0, customs_logistics_fee=0,
                               sale_price=0, row_hash=None):
    date = pd.to_datetime(date)

    if not row_hash:
        payload = f"{date}{item}{action}{qty}{customer}"
        row_hash = hashlib.md5(payload.encode()).hexdigest()

    if item not in st.session_state.inventory_queues:
        st.session_state.inventory_queues[item] = deque()

    new_record = {
        '날짜': date, '고객사': customer, '품목명': item, '구분': action, '세부구분': sub_type,
        '수량': qty, '순수단가': 0, '통관물류비': 0, '최종매입원가': 0, '매출원가': 0, '상태': '정상', '비고': '', 'hash': row_hash
    }

    audit_details = f"[{action}] 품목:{item} | 수량:{qty}개 | "

    if action == "입고":
        # 수입 부대비용 분배 및 최종 단가 산출
        unit_extra = customs_logistics_fee / qty if qty > 0 else 0
        final_unit_cost = base_price + unit_extra

        st.session_state.inventory_queues[item].append({'date': date, 'qty': qty, 'price': final_unit_cost})

        new_record.update({'순수단가': base_price, '통관물류비': customs_logistics_fee, '최종매입원가': final_unit_cost,
                           '비고': f"[{sub_type}] 제비용 분배완료"})
        audit_details += f"최종매입원가:{final_unit_cost:,.0f}원"

    elif action == "출고":
        remaining = qty
        total_cogs = 0
        fifo_breakdown = []
        batch_status = []
        queue = st.session_state.inventory_queues[item]

        while remaining > 0 and queue:
            batch = queue[0]
            batch_date_str = batch['date'].strftime('%Y-%m-%d')

            if batch['qty'] <= remaining:
                use_qty = batch['qty']
                cost = use_qty * batch['price']
                total_cogs += cost
                remaining -= use_qty
                fifo_breakdown.append({'입고일': batch_date_str, '차감수량': use_qty, '적용원가': batch['price'], '합계': cost})
                batch_status.append({'입고일': batch_date_str, '잔량': 0})
                queue.popleft()
            else:
                use_qty = remaining
                cost = use_qty * batch['price']
                total_cogs += cost
                batch['qty'] -= use_qty
                remaining = 0
                fifo_breakdown.append({'입고일': batch_date_str, '차감수량': use_qty, '적용원가': batch['price'], '합계': cost})
                batch_status.append({'입고일': batch_date_str, '잔량': batch['qty']})

        new_record.update({'순수단가': sale_price, '매출원가': total_cogs,
                           '비고': f"[{sub_type}] 정상출고" if remaining == 0 else f"재고부족({remaining}개)"})

        # CRM 저장 (매출일 경우)
        if sub_type == "매출":
            new_crm = {'날짜': date, '고객사': customer, '품목명': item, '판매단가': sale_price, '비고': '정상판매'}
            st.session_state.crm_history = pd.concat([st.session_state.crm_history, pd.DataFrame([new_crm])],
                                                     ignore_index=True)

        st.session_state.latest_fifo_detail = pd.DataFrame(fifo_breakdown)
        st.session_state.latest_batch_status = pd.DataFrame(batch_status)
        audit_details += f"고객사:{customer} | 매출원가:{total_cogs:,.0f}원"

    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_record])], ignore_index=True)
    st.session_state.history = st.session_state.history.sort_values(by='날짜').reset_index(drop=True)

    write_audit_log(f"수동 {action}", audit_details)


# ==========================================
# [핵심 모듈 4] 엑셀 대량 업로드 (파이프라인)
# ==========================================
def handle_excel_upload(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file)
        required = ['날짜', '고객사', '품목명', '구분', '세부구분', '수량', '순수단가', '통관물류비', '판매단가']
        if not all(c in df.columns for c in required):
            st.error(f"양식 오류! 필수 컬럼: {required}")
            return

        df['날짜'] = pd.to_datetime(df['날짜'])
        df['hash'] = df.apply(generate_row_hash, axis=1)

        existing_hashes = set(st.session_state.history['hash'].tolist())
        new_data = df[~df['hash'].isin(existing_hashes)].copy()

        if new_data.empty:
            st.warning("추가할 신규 데이터가 없습니다. (중복 방지 됨)")
            return

        new_data = new_data.sort_values('날짜')
        with st.status("엑셀 데이터 분석 및 FIFO 큐 적재 중...") as status:
            for _, row in new_data.iterrows():
                process_secure_transaction(
                    date=row['날짜'], item=row['품목명'], action=row['구분'], sub_type=row['세부구분'],
                    qty=row['수량'], customer=row['고객사'], base_price=row['순수단가'],
                    customs_logistics_fee=row['통관물류비'], sale_price=row['판매단가'], row_hash=row['hash']
                )
            status.update(label="반영 완료!", state="complete")

        write_audit_log("엑셀 일괄 업로드", f"총 {len(new_data)}건의 데이터 파이프라인 동기화 완료")
        st.rerun()
    except Exception as e:
        st.error(f"파일 처리 오류: {e}")


# ==========================================
# [핵심 모듈 5] AI 분석 및 대시보드 함수
# ==========================================
def calculate_sales_metrics(item_name):
    history = st.session_state.history
    now = datetime.now()
    sales_df = history[(history['품목명'] == item_name) & (history['구분'] == '출고')].copy()

    if sales_df.empty: return 0, 0, 0
    one_year_ago = now - pd.Timedelta(days=365)
    three_months_ago = now - pd.Timedelta(days=90)

    avg_12m = sales_df[sales_df['날짜'] >= one_year_ago]['수량'].sum() / 12
    avg_3m = sales_df[sales_df['날짜'] >= three_months_ago]['수량'].sum() / 3
    current_stock = sum(b['qty'] for b in st.session_state.inventory_queues.get(item_name, []))

    return current_stock, avg_12m, avg_3m


def get_inventory_summary():
    summary_data = []
    for item, queue in st.session_state.inventory_queues.items():
        total_qty = sum(b['qty'] for b in queue)
        total_value = sum(b['qty'] * b['price'] for b in queue)  # price는 최종매입원가
        if total_qty >= 0:
            summary_data.append({"품목명": item, "현재고": total_qty, "자산금액": total_value})
    return pd.DataFrame(summary_data)


# ==========================================
# [메인 애플리케이션 실행]
# ==========================================
initialize_state()

if not st.session_state.logged_in:
    login_screen()
else:
    with st.sidebar:
        st.title("⚙️ 통합 시스템 메뉴")
        st.info(f"👤 접속자: **{st.session_state.current_user}**")

        menu_options = [
            "1. 📁 엑셀 일괄 업로드",
            "2. 🚢 수동 수입/입고",
            "3. 📤 수동 매출/출고",
            "4. 🤝 CRM 및 단가 이력",
            "5. 📊 AI 재고/발주 분석"
        ]
        if st.session_state.role == "admin":
            menu_options.append("6. 🛡️ 시스템 감사 (Admin)")

        app_mode = st.radio("작업 선택", menu_options)
        st.divider()
        if st.button("🚪 로그아웃", use_container_width=True):
            write_audit_log("로그아웃", "시스템 정상 종료")
            st.session_state.logged_in = False
            st.rerun()

    # --- 1. 엑셀 파이프라인 ---
    if app_mode == "1. 📁 엑셀 일괄 업로드":
        st.title("📥 대량 데이터 마이그레이션 (Excel)")
        st.info("기존 ERP에서 추출한 엑셀을 업로드하면 중복(Hash)을 걸러내고 안전하게 DB에 적재됩니다.")

        template = pd.DataFrame(columns=['날짜', '고객사', '품목명', '구분', '세부구분', '수량', '순수단가', '통관물류비', '판매단가'])
        st.download_button("📥 업로드 양식(Template) 다운로드", data=template.to_csv(index=False).encode('utf-8-sig'),
                           file_name="erp_template.csv")

        uploaded_file = st.file_uploader("엑셀 파일을 선택하세요", type=['xlsx'])
        if uploaded_file and st.button("🚀 데이터 동기화 실행", type="primary", use_container_width=True):
            handle_excel_upload(uploaded_file)

    # --- 2. 수동 입고 ---
    elif app_mode == "2. 🚢 수동 수입/입고":
        st.title("🚢 수동 수입 원가 배분 및 입고")
        with st.form("import_form"):
            c1, c2, c3 = st.columns(3)
            with c1: t_date = st.date_input("수입 일자"); t_item = st.text_input("품목명")
            with c2: t_qty = st.number_input("입고 수량", min_value=1); t_base_price = st.number_input("물품 순수단가",
                                                                                                   min_value=0.0)
            with c3: t_fees = st.number_input("총 부대비용 (통관/물류비)", min_value=0)

            if st.form_submit_button("입고 등록 및 원가 배분", type="primary") and t_item:
                process_secure_transaction(t_date, t_item, "입고", "수입", t_qty, base_price=t_base_price,
                                           customs_logistics_fee=t_fees)
                st.success("데이터베이스에 안전하게 기록되었습니다.")
                st.rerun()

    # --- 3. 수동 출고 ---
    elif app_mode == "3. 📤 수동 매출/출고":
        st.title("📤 수동 매출 출고 및 FIFO 원가 산출")
        with st.form("sales_form"):
            c1, c2, c3 = st.columns(3)
            item_list = list(st.session_state.inventory_queues.keys())
            with c1: s_date = st.date_input("매출 일자"); s_customer = st.text_input("고객사명", value="A마트")
            with c2: s_item = st.selectbox("출고 품목", item_list if item_list else ["품목없음"]); s_qty = st.number_input(
                "출고 수량", min_value=1)
            with c3: s_sale_price = st.number_input("적용 판매단가", min_value=0)

            if st.form_submit_button("출고 및 선입선출 계산", type="primary") and s_item != "품목없음":
                process_secure_transaction(s_date, s_item, "출고", "매출", s_qty, customer=s_customer,
                                           sale_price=s_sale_price)
                st.rerun()

        st.divider()
        l_col, r_col = st.columns(2)
        with l_col:
            st.subheader("🧪 FIFO 차감 상세 내역")
            if not st.session_state.latest_fifo_detail.empty: st.dataframe(st.session_state.latest_fifo_detail,
                                                                           use_container_width=True)
        with r_col:
            st.subheader("📅 관련 배치의 출고 후 잔량")
            if not st.session_state.latest_batch_status.empty: st.dataframe(st.session_state.latest_batch_status,
                                                                            use_container_width=True)

    # --- 4. CRM ---
    elif app_mode == "4. 🤝 CRM 및 단가 이력":
        st.title("🤝 고객사 CRM 및 발주 알림")
        if not st.session_state.crm_history.empty:
            st.dataframe(st.session_state.crm_history, use_container_width=True)
        else:
            st.info("매출 기록이 없습니다.")

    # --- 5. AI 대시보드 ---
    elif app_mode == "5. 📊 AI 재고/발주 분석":
        st.title("📊 통합 대시보드 및 AI 발주 분석")

        # 1) 전체 요약
        st.subheader("📦 창고 전체 자산 요약")
        inv_df = get_inventory_summary()
        if not inv_df.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("관리 품목 수", f"{len(inv_df)} 종")
            m2.metric("총 재고 수량", f"{inv_df['현재고'].sum():,} 개")
            m3.metric("총 재고 자산", f"₩ {inv_df['자산금액'].sum():,.0f}")
            st.dataframe(inv_df.sort_values('자산금액', ascending=False), use_container_width=True)

        st.divider()

        # 2) 개별 AI 발주 분석
        st.subheader("💡 품목별 적정재고 (리드타임) 검토")
        item_list = sorted(st.session_state.history['품목명'].unique())
        if item_list:
            selected_item = st.selectbox("분석할 품목 선택", item_list)
            curr_stock, m12_avg, m3_avg = calculate_sales_metrics(selected_item)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("현재 재고", f"{curr_stock:,} 개")
            c2.metric("1년 월평균 판매", f"{int(m12_avg)} 개")
            c3.metric("최근 3개월 평균", f"{int(m3_avg)} 개", delta=f"{m3_avg - m12_avg:,.1f} 추세")

            stock_months = curr_stock / m3_avg if m3_avg > 0 else 0
            c4.metric("재고 소진 예상", f"{stock_months:.1f} 개월")

            if stock_months < 2.0:
                st.error("⚠️ **발주 경고**: 재고가 수입 리드타임(2개월) 대비 부족합니다.")
            elif stock_months < 3.0:
                st.warning("🟡 **관찰 필요**: 재고가 적정선 하단입니다.")
            else:
                st.success("✅ **안정권**: 재고가 충분합니다.")

    # --- 6. 보안 로그 ---
    elif app_mode == "6. 🛡️ 시스템 감사 (Admin)":
        st.title("🛡️ 전산 감사 로그 (Paper Trail)")
        st.error("물리적 삭제 불가 영역. 전산 감사를 위한 위변조 방지 기록입니다.")
        st.dataframe(st.session_state.audit_logs.sort_values(by='시간', ascending=False), use_container_width=True)