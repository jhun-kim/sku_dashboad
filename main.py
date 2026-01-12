import pandas as pd
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional


#

class FIFOCostCalculator:
    """기능 1: 선입선출(FIFO) 방식의 원가 계산 및 재고 관리 담당"""

    def __init__(self):
        # 품목별 입고 내역을 저장하는 큐: { "품목A": deque([배치1, 배치2, ...]) }
        self._inventory_queues: Dict[str, deque] = {}
        # 출고 처리 결과 저장
        self.sales_records = []

    def add_stock(self, item_name: str, qty: int, unit_price: float, date: datetime):
        """입고 기록을 시스템에 등록"""
        if item_name not in self._inventory_queues:
            self._inventory_queues[item_name] = deque()

        self._inventory_queues[item_name].append({
            'qty': qty,
            'price': unit_price,
            'date': date
        })

    def calculate_out_cost(self, item_name: str, qty_to_sell: int, date: datetime) -> Dict:
        """
        출고 시 FIFO 로직 적용 (여러 배치에 걸친 원가 계산 포함)
        """
        remaining_needed = qty_to_sell
        total_cogs = 0.0  # 매출원가 합계
        batches_used = []

        if item_name not in self._inventory_queues or not self._inventory_queues[item_name]:
            return self._record_sale(date, item_name, qty_to_sell, 0, "재고없음")

        # 선입선출 핵심 로직 시작
        while remaining_needed > 0 and self._inventory_queues[item_name]:
            # 가장 오래된 배치 확인
            oldest_batch = self._inventory_queues[item_name][0]

            if oldest_batch['qty'] <= remaining_needed:
                # 1. 현재 배치를 전부 소진하는 경우
                use_qty = oldest_batch['qty']
                total_cogs += use_qty * oldest_batch['price']
                remaining_needed -= use_qty
                self._inventory_queues[item_name].popleft()  # 큐에서 제거
            else:
                # 2. 현재 배치의 일부만 사용하는 경우 (나머지는 큐에 유지)
                use_qty = remaining_needed
                total_cogs += use_qty * oldest_batch['price']
                oldest_batch['qty'] -= use_qty
                remaining_needed = 0

            batches_used.append(f"{use_qty}개(단가:{oldest_batch['price']:,.0f})")

        status = "정상" if remaining_needed == 0 else f"재고부족({remaining_needed}개)"
        return self._record_sale(date, item_name, qty_to_sell, total_cogs, status, ", ".join(batches_used))

    def _record_sale(self, date, item, qty, cost, status, details=""):
        record = {
            '날짜': date, '품목명': item, '출고수량': qty,
            '매출원가': cost, '상태': status, '비고': details
        }
        self.sales_records.append(record)
        return record

    def get_current_stock_level(self, item_name: str) -> int:
        """현재 특정 품목의 남은 총 재고량 반환"""
        return sum(batch['qty'] for batch in self._inventory_queues.get(item_name, []))


class InventoryReporter:
    """기능 2: 재고 현황 분석 및 리포트 생성 담당"""

    @staticmethod
    def print_analysis(master_df: pd.DataFrame, calculator: FIFOCostCalculator):
        print("\n" + "=" * 85)
        print(f"{'품목명':<15} | {'현재고':>7} | {'3개월평균':>10} | {'재고보유월수':>10} | {'상태'}")
        print("-" * 85)

        for _, row in master_df.iterrows():
            item = row['품목명']
            current_qty = calculator.get_current_stock_level(item)
            avg_3m = row['3개월_월평균판매']

            # 재고 보유 가능 월수 계산
            months_left = current_qty / avg_3m if avg_3m > 0 else 0
            status = "🚨 발주필요" if months_left < 1.5 else "✅ 안정"

            print(f"{item:<15} | {current_qty:>9,} | {avg_3m:>11.1f} | {months_left:>12.1f}개월 | {status}")
        print("=" * 85)


class InventorySystem:
    """전체 시스템을 조율하는 오케스트레이터"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.calculator = FIFOCostCalculator()
        self.reporter = InventoryReporter()

    def run(self):
        # 1. 데이터 로드
        df_history = pd.read_excel(self.file_path, sheet_name='거래이력')
        df_master = pd.read_excel(self.file_path, sheet_name='재고분석기준')

        # 날짜순 정렬 (FIFO 처리를 위해 필수)
        df_history = df_history.sort_values(by='날짜')

        # 2. 통합 처리 (입고와 출고를 날짜 순서대로 처리)
        for _, row in df_history.iterrows():
            if row['구분'] == '입고':
                self.calculator.add_stock(row['품목명'], row['수량'], row['단가'], row['날짜'])
        for _, row in df_history.iterrows():
            if row['구분'] == '출고':
                self.calculator.calculate_out_cost(row['품목명'], row['수량'], row['날짜'])

        # 3. 리포트 출력
        self.reporter.print_analysis(df_master, self.calculator)

        # 4. 결과 저장
        output_df = pd.DataFrame(self.calculator.sales_records)
        output_df.to_excel('inventory_cogs_final.xlsx', index=False)
        print("\n💾 매출원가 계산 결과가 'inventory_cogs_final.xlsx'로 저장되었습니다.")


# --- 실행부 ---
if __name__ == "__main__":
    system = InventorySystem('inventory_test_data.xlsx')
    system.run()