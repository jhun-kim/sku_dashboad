import streamlit as st
import pandas as pd
from io import BytesIO

# 1. 페이지 설정
st.set_page_config(page_title="재고 트래킹 시스템", layout="wide")

# 사이드바 너비 조절 (이전 답변 참고)
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { min-width: 300px; max-width: 300px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# 2. 엑셀 파일 업로드 기능
st.sidebar.header("📂 데이터 업로드")
uploaded_file = st.sidebar.file_uploader("엑셀 파일을 선택하세요", type=["xlsx"])

if uploaded_file:
    # 데이터 불러오기
    df = pd.read_excel(uploaded_file)

    # 날짜 형식 변환
    df['날짜'] = pd.to_datetime(df['날짜'])

    # 3. 필터링 UI
    st.sidebar.header("🔍 필터 설정")
    # items = st.sidebar.multiselect("품목 선택", options=df['품목명'].unique(), default=df['품목명'].unique())
    # items = df['품목명'].unique()
    target_item = st.sidebar.selectbox("품목 선택", df['품목명'].unique())
    date_range = st.sidebar.date_input("날짜 범위", [df['날짜'].min(), df['날짜'].max()])

    # 데이터 필터링 로직 수정
    if len(date_range) == 2:  # 시작일과 종료일이 모두 선택되었을 때만 실행
        start_date, end_date = date_range

        # 수정 포인트:
        # - target_item이 단일값이므로 == 를 사용하거나 [target_item] 리스트화 필요
        # - 날짜 비교 시 dt.date와 date_range 요소를 비교
        mask = (df['품목명'] == target_item) & \
               (df['날짜'].dt.date >= start_date) & \
               (df['날짜'].dt.date <= end_date)

        filtered_df = df.loc[mask].sort_values(by='날짜')
    else:
        # 날짜가 한쪽만 선택된 경우 빈 데이터프레임 혹은 기본 데이터 표시
        filtered_df = pd.DataFrame(columns=df.columns)

    # 4. 상단 요약 지표 (Metrics)
    st.title("📦 재고 트래킹 대시보드")

    col1, col2, col3 = st.columns(3)
    total_in = filtered_df[filtered_df['구분'] == '입고']['수량'].sum()
    total_out = filtered_df[filtered_df['구분'] == '출고']['수량'].sum()
    current_stock = total_in - total_out

    col1.metric("총 입고량", f"{total_in:,} 개")
    col2.metric("총 출고량", f"{total_out:,} 개")
    col3.metric("현재 재고액(예상)", f"{current_stock:,} 개", delta_color="normal")

    # 5. 데이터 테이블 표시
    st.subheader("📋 상세 내역")
    st.dataframe(filtered_df, use_container_width=True)

    # 6. 품목별 재고 현황 요약 테이블
    st.subheader("📊 품목별 수불 현황")
    summary = df.groupby(['품목명', '구분'])['수량'].sum().unstack(fill_value=0)
    if '입고' not in summary: summary['입고'] = 0
    if '출고' not in summary: summary['출고'] = 0
    summary['현재고'] = summary['입고'] - summary['출고']
    st.table(summary)


    # 7. 엑셀 다운로드 기능
    def to_excel(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        return output.getvalue()


    excel_data = to_excel(filtered_df)
    st.download_button(
        label="📥 필터링된 결과 엑셀 다운로드",
        data=excel_data,
        file_name='inventory_report.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

else:
    st.info("왼쪽 사이드바에서 엑셀 파일을 업로드해 주세요.")
    # 샘플 데이터 형식 안내
    st.write("엑셀 파일은 아래와 같은 컬럼을 포함해야 합니다:")
    st.write(pd.DataFrame({
        '날짜': ['2023-01-01'], '품목명': ['사과'], '구분': ['입고'], '수량': [100], '단가': [1000]
    }))