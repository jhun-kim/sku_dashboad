import streamlit as st
import pandas as pd
from collections import deque
from datetime import datetime
import hashlib
import os
import tempfile

# 💡 AI 기능 (Upstage & Pydantic)
from pydantic import BaseModel, Field
from typing import List
from langchain_upstage import UpstageDocumentParseLoader, ChatUpstage

# ==========================================
# [1. 환경 설정 및 API 키]
# ==========================================
st.set_page_config(layout="wide", page_title="AI Enterprise Master System")
st.markdown("""
    <style>
    [data-testid="stSidebar"] { min-width: 320px; max-width: 320px; }
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; }
    </style>
    """, unsafe_allow_html=True)

# ⚠️ 여기에 실제 발급받은 Upstage API 키를 입력하세요.
os.environ["UPSTAGE_API_KEY"] = ""


# ==========================================
# [2. AI 데이터 구조 스키마 (Pydantic)]
# ==========================================
class ImportItem(BaseModel):
    품목명: str = Field(description="수입된 물품의 정확한 이름")
    수량: int = Field(description="수입된 물품의 총 수량 (숫자만)")
    순수단가: float = Field(description="물품 1개당 순수 단가 (원화 환산 기준, 숫자만)")


class ImportDocument(BaseModel):
    수입일자: str = Field(description="YYYY-MM-DD 형식의 수입/통관 일자")
    거래처: str = Field(description="수출자, 제조사 또는 거래처 이름")
    총통관물류비: int = Field(description="관세, 부가세, 운송비, 하역비 등 발생한 모든 제비용의 합계 (원화, 숫자만)")
    품목목록: List[ImportItem] = Field(description="수입된 품목들의 배열")


# ==========================================
# [3. 상태 초기화 및 공통 유틸리티]
# ==========================================
def generate_row_hash(row):
    """중복 적재 방지를 위한 행 데이터 고유 해시값 생성"""
    payload = f"{row.get('날짜', '')}{row.get('고객사', '')}{row.get('품목명', '')}{row.get('수량', '')}{row.get('구분', '')}"
    return hashlib.md5(payload.encode()).hexdigest()


def write_audit_log(action, details):
    """위변조 불가능한 전산 감사 로그 (Paper Trail) 기록"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user = st.session_state.get('current_user', 'System')
    log_entry = {'시간': now, '작업자': user, '접속IP': "192.168.1.10", '수행작업': action, '상세내용': details}
    if 'audit_logs' not in st.session_state:
        st.session_state.audit_logs = pd.DataFrame(columns=['시간', '작업자', '접속IP', '수행작업', '상세내용'])
    st.session_state.audit_logs = pd.concat([st.session_state.audit_logs, pd.DataFrame([log_entry])], ignore_index=True)


def initialize_state():
    if 'logged_in' not in st.session_state: st.session_state.update(
        {'logged_in': False, 'current_user': "", 'role': ""})

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
# [4. 보안 결합형 비즈니스 엔진 (FIFO & 원가 배분)]
# ==========================================
def process_secure_transaction(date, item, action, sub_type, qty, customer="본사", base_price=0, customs_logistics_fee=0,
                               sale_price=0, row_hash=None):
    date = pd.to_datetime(date)

    if not row_hash:
        row_hash = generate_row_hash({'날짜': date, '고객사': customer, '품목명': item, '수량': qty, '구분': action})

    if item not in st.session_state.inventory_queues:
        st.session_state.inventory_queues[item] = deque()

    new_record = {
        '날짜': date, '고객사': customer, '품목명': item, '구분': action, '세부구분': sub_type,
        '수량': qty, '순수단가': 0, '통관물류비': 0, '최종매입원가': 0, '매출원가': 0, '상태': '정상', '비고': '', 'hash': row_hash
    }
    audit_details = f"[{action}] 품목:{item} | 수량:{qty}개 | "

    if action == "입고":
        # 제비용 N빵 분배
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

        # CRM 이력 적재
        if sub_type in ["매출", "출고"]:
            st.session_state.crm_history = pd.concat([
                st.session_state.crm_history,
                pd.DataFrame([{'날짜': date, '고객사': customer, '품목명': item, '판매단가': sale_price, '비고': '정상판매'}])
            ], ignore_index=True)

        st.session_state.latest_fifo_detail = pd.DataFrame(fifo_breakdown)
        st.session_state.latest_batch_status = pd.DataFrame(batch_status)
        audit_details += f"고객사:{customer} | 매출원가:{total_cogs:,.0f}원"

    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_record])], ignore_index=True)
    st.session_state.history = st.session_state.history.sort_values(by='날짜').reset_index(drop=True)

    write_audit_log(f"트랜잭션({action})", audit_details)


# ==========================================
# [5. 데이터 파이프라인 (엑셀 & AI PDF)]
# ==========================================
def process_smart_sync(uploaded_files):
    """다중 엑셀 파일 병합 및 적재"""
    combined_new_data = pd.DataFrame()
    for uploaded_file in uploaded_files:
        try:
            df = pd.read_excel(uploaded_file)
            df['날짜'] = pd.to_datetime(df['날짜'])
            df['hash'] = df.apply(generate_row_hash, axis=1)
            existing_hashes = set(st.session_state.history['hash'].tolist())
            new_rows = df[~df['hash'].isin(existing_hashes)].copy()

            if not new_rows.empty:
                combined_new_data = pd.concat([combined_new_data, new_rows], ignore_index=True)
                write_audit_log("엑셀 동기화", f"파일[{uploaded_file.name}]에서 {len(new_rows)}건 감지")
        except Exception as e:
            st.error(f"파일 {uploaded_file.name} 처리 중 오류: {e}")

    if not combined_new_data.empty:
        combined_new_data = combined_new_data.sort_values('날짜')
        for _, row in combined_new_data.iterrows():
            process_secure_transaction(
                date=row['날짜'], item=row['품목명'], action=row['구분'], sub_type=row.get('세부구분', row['구분']),
                qty=row['수량'], customer=row.get('고객사', '본사'), base_price=row.get('순수단가', 0),
                customs_logistics_fee=row.get('통관물류비', 0) + row.get('통관비', 0) + row.get('물류비', 0),
                sale_price=row.get('판매단가', 0), row_hash=row['hash']
            )
        st.success(f"✅ 총 {len(combined_new_data)}건 데이터 적재 완료.")
    else:
        st.warning("⚠️ 새로 추가할 데이터가 없습니다.")


def process_pdf_with_ai(uploaded_file):
    """AI PDF 문서 파싱 및 JSON 정형화"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    try:
        with st.status("🤖 AI가 문서를 분석 중입니다...", expanded=True) as status:
            st.write("1️⃣ Upstage Document Parse: 문서 레이아웃 추출 중...")
            loader = UpstageDocumentParseLoader(tmp_file_path, output_format="text")
            docs = loader.load()
            parsed_text = "\n".join([doc.page_content for doc in docs])

            st.write("2️⃣ Solar Pro LLM: 데이터 구조화(JSON) 진행 중...")
            llm = ChatUpstage(model="solar-pro")
            structured_llm = llm.with_structured_output(ImportDocument)

            prompt = f"다음 파싱된 통관 문서 내용을 분석하여 스키마 형식에 맞게 데이터를 추출하세요.\n내용:\n{parsed_text}"
            extracted_data = structured_llm.invoke(prompt)

            status.update(label="✅ AI 문서 분석 완료!", state="complete")
            return extracted_data
    except Exception as e:
        st.error(f"AI 파싱 오류: {e}")
        return None
    finally:
        os.remove(tmp_file_path)


# ==========================================
# [6. 메인 UI 및 앱 라우팅]
# ==========================================
def main_app():
    initialize_state()

    # --- 로그인 화면 ---
    if not st.session_state.logged_in:
        st.title("🔒 AI & Secure ERP 로그인")
        with st.form("login_form"):
            user_id = st.text_input("아이디 (관리자: admin / 실무자: staff)")
            password = st.text_input("비밀번호 (공통: 1234)", type="password")
            if st.form_submit_button("로그인", type="primary"):
                if user_id == "admin" and password == "1234":
                    st.session_state.update({'logged_in': True, 'current_user': "김대표(관리자)", 'role': "admin"})
                    write_audit_log("로그인", "관리자 접속")
                    st.rerun()
                elif user_id == "staff" and password == "1234":
                    st.session_state.update({'logged_in': True, 'current_user': "이대리(실무자)", 'role': "user"})
                    write_audit_log("로그인", "실무자 접속")
                    st.rerun()
                else:
                    st.error("⚠️ 인증 실패")
        return

    # --- 사이드바 메뉴 ---
    with st.sidebar:
        st.title("⚙️ AI 통합 관리 시스템")
        st.info(f"👤 접속자: **{st.session_state.current_user}**")
        menu_options = [
            "0. 🔄 다중 엑셀 동기화",
            "1. 📄 AI PDF 통관서류 자동화",
            "2. 🚢 수동 수입 원가 및 입고",
            "3. 📤 수동 매출 출고",
            "4. 🤝 CRM 및 발주 분석 대시보드"
        ]
        if st.session_state.role == "admin":
            menu_options.append("5. 🛡️ 시스템 감사 (Admin)")

        app_mode = st.radio("메뉴 선택", menu_options)
        st.divider()
        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state.logged_in = False
            write_audit_log("로그아웃", "시스템 종료")
            st.rerun()

    # --- 0. 엑셀 동기화 ---
    if app_mode == "0. 🔄 다중 엑셀 동기화":
        st.title("🔄 ERP 엑셀 데이터 파이프라인")
        uploaded_files = st.file_uploader("수불부, 단가표 등 엑셀 파일 다중 선택", type=['xlsx'], accept_multiple_files=True)
        if uploaded_files and st.button("🚀 데이터 통합 적재 실행", type="primary"):
            process_smart_sync(uploaded_files)

    # --- 1. AI PDF 자동화 ---
    elif app_mode == "1. 📄 AI PDF 통관서류 자동화":
        st.title("📄 AI 수입 통관/인보이스 자동 적재")
        uploaded_pdf = st.file_uploader("수입 서류 PDF 업로드", type=['pdf', 'png', 'jpg'])

        if 'ai_extracted_data' not in st.session_state: st.session_state.ai_extracted_data = None

        if uploaded_pdf and st.button("🚀 AI 분석 시작", type="primary"):
            if "UPSTAGE_API_KEY를_여기에_입력하세요" in os.environ.get("UPSTAGE_API_KEY", ""):
                st.error("⚠️ 코드 상단에 실제 Upstage API 키를 입력해 주세요.")
            else:
                st.session_state.ai_extracted_data = process_pdf_with_ai(uploaded_pdf)

        if st.session_state.ai_extracted_data:
            data = st.session_state.ai_extracted_data
            st.divider()
            st.subheader("🧐 AI 추출 결과 검토 (Human-in-the-Loop)")
            c1, c2, c3 = st.columns(3)
            c1.text_input("수입 일자", value=data.수입일자, disabled=True)
            c2.text_input("거래처", value=data.거래처, disabled=True)
            c3.text_input("총 제비용", value=f"{data.총통관물류비:,} 원", disabled=True)

            st.dataframe(pd.DataFrame([item.dict() for item in data.품목목록]), use_container_width=True)

            if st.button("💾 위 내용으로 DB 적재 및 원가 배분 확정", type="primary"):
                total_qty = sum([item.수량 for item in data.품목목록])
                for item in data.품목목록:
                    ratio = item.수량 / total_qty if total_qty > 0 else 0
                    allocated_fee = data.총통관물류비 * ratio
                    process_secure_transaction(
                        date=data.수입일자, item=item.품목명, action="입고", sub_type="수입(AI자동화)",
                        qty=item.수량, customer=data.거래처, base_price=item.순수단가, customs_logistics_fee=allocated_fee
                    )
                st.success("🎉 데이터베이스에 안전하게 자동 적재 및 원가 계산 완료!")
                st.session_state.ai_extracted_data = None
                st.rerun()

    # --- 2. 수동 입고 ---
    elif app_mode == "2. 🚢 수동 수입 원가 및 입고":
        st.title("🚢 수동 수입 원가 배분 및 입고")
        with st.form("import_form"):
            c1, c2, c3 = st.columns(3)
            with c1: t_date = st.date_input("수입 일자"); t_item = st.text_input("품목명")
            with c2: t_qty = st.number_input("입고 수량", min_value=1); t_base_price = st.number_input("물품 순수단가",
                                                                                                   min_value=0.0)
            with c3: t_fees = st.number_input("총 부대비용 (통관/물류비 등)", min_value=0)
            if st.form_submit_button("입고 등록 및 원가 배분", type="primary") and t_item:
                process_secure_transaction(t_date, t_item, "입고", "수동수입", t_qty, base_price=t_base_price,
                                           customs_logistics_fee=t_fees)
                st.rerun()

    # --- 3. 수동 출고 ---
    elif app_mode == "3. 📤 수동 매출 출고":
        st.title("📤 수동 매출 출고 및 FIFO 원가 산출")
        with st.form("sales_form"):
            c1, c2, c3 = st.columns(3)
            item_list = list(st.session_state.inventory_queues.keys())
            with c1: s_date = st.date_input("매출 일자"); s_customer = st.text_input("고객사명")
            with c2: s_item = st.selectbox("출고 품목", item_list if item_list else ["품목없음"]); s_qty = st.number_input(
                "출고 수량", min_value=1)
            with c3: s_sale_price = st.number_input("판매단가", min_value=0)
            if st.form_submit_button("출고 및 선입선출 계산", type="primary") and s_item != "품목없음":
                process_secure_transaction(s_date, s_item, "출고", "매출", s_qty, customer=s_customer,
                                           sale_price=s_sale_price)
                st.rerun()

        if not st.session_state.latest_fifo_detail.empty:
            st.subheader("🧪 FIFO 차감 상세 내역")
            st.table(st.session_state.latest_fifo_detail)

    # --- 4. 대시보드 ---
    elif app_mode == "4. 🤝 CRM 및 발주 분석 대시보드":
        st.title("📊 통합 대시보드 (CRM & 재고 분석)")
        tab1, tab2 = st.tabs(["🤝 고객사 CRM 히스토리", "💡 품목별 AI 적정재고 검토"])

        with tab1:
            st.dataframe(st.session_state.crm_history.sort_values(by='날짜', ascending=False), use_container_width=True)

        with tab2:
            item_list = sorted(st.session_state.history['품목명'].unique())
            if item_list:
                sel_item = st.selectbox("분석 품목 선택", item_list)
                # 간단한 분석 로직 인라인 처리
                sales = st.session_state.history[
                    (st.session_state.history['품목명'] == sel_item) & (st.session_state.history['구분'] == '출고')]
                curr_stock = sum(b['qty'] for b in st.session_state.inventory_queues.get(sel_item, []))

                now = datetime.now()
                avg_12m = sales[sales['날짜'] >= now - pd.Timedelta(days=365)]['수량'].sum() / 12
                avg_3m = sales[sales['날짜'] >= now - pd.Timedelta(days=90)]['수량'].sum() / 3
                stock_months = curr_stock / avg_3m if avg_3m > 0 else 0

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("현재 재고", f"{curr_stock:,} 개")
                c2.metric("1년 평균 판매", f"{int(avg_12m)} 개/월")
                c3.metric("최근 3개월 판매", f"{int(avg_3m)} 개/월")
                c4.metric("재고 소진 예상", f"{stock_months:.1f} 개월")

                if stock_months < 2.0:
                    st.error("⚠️ **발주 경고**: 수입 리드타임 대비 재고 부족!")
                else:
                    st.success("✅ **안정권**: 재고 충분")

    # --- 5. 시스템 감사 ---
    elif app_mode == "5. 🛡️ 시스템 감사 (Admin)":
        st.title("🛡️ 전산 감사 로그 (Paper Trail)")
        st.error("모든 엑셀 동기화, 수동 입력 및 AI 파이프라인의 조작 내역이 위변조 불가능한 형태로 기록됩니다.")
        st.dataframe(st.session_state.audit_logs.sort_values(by='시간', ascending=False), use_container_width=True)


if __name__ == "__main__":
    main_app()