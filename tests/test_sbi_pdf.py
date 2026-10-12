import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from decimal import Decimal
from expense_tracker.sbi_pdf import parse_table_rows, is_likely_amount_token, is_summary_row

class SbiPdfTests(unittest.TestCase):
    def test_7col_table_without_explicit_headers(self):
        table = [
            ['', '', '', '', '', '', 'Balance'],
            ['01/09/2026', '01/09/2026', 'UPI/DR/123/Swiggy', '-', '330.00', '-', '50,000.00'],
            ['02/09/2026', '02/09/2026', 'UPI/CR/456/Refund', '-', '-', '100.00', '50,100.00'],
        ]
        txns = parse_table_rows([table])
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0]['txn_date'], '2026-09-01')
        self.assertEqual(txns[0]['debit'], Decimal('330.00'))
        self.assertEqual(txns[0]['credit'], Decimal('0'))
        self.assertIsNone(txns[0]['reference'])
        self.assertEqual(txns[1]['txn_date'], '2026-09-02')
        self.assertEqual(txns[1]['credit'], Decimal('100.00'))

    def test_summary_table_exclusion(self):
        txn_table = [
            ['', '', '', '', '', '', 'Balance'],
            ['01/09/2026', '01/09/2026', 'UPI/DR/123/Swiggy', '-', '330.00', '-', '50,000.00'],
        ]
        summary_table = [
            ['Statement Summary : 01-09-2026 To 14-09-2026', '', '', '', '', ''],
            ['Brought Forward( )', 'Dr Count', 'Cr Count', 'Total Debits( )', 'Total Credits( )', 'Closing Balance( )'],
            ['50,330.00CR', '1', '0', '330.00', '0.00', '50,000.00CR'],
        ]
        txns = parse_table_rows([txn_table, summary_table])
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]['description'], 'UPI/DR/123/Swiggy')
        self.assertNotIn('Statement Summary', txns[0]['description'])
        self.assertNotIn('50,330.00CR', txns[0]['description'])

    def test_page_header_not_treated_as_continuation(self):
        table_p1 = [
            ['', '', '', '', '', '', 'Balance'],
            ['01/09/2026', '01/09/2026', 'UPI/DR/123/Store', '-', '150.00', '-', '50,000.00'],
        ]
        table_p2 = [
            ['', '', '', '', '', '', 'Balance'],
            ['02/09/2026', '02/09/2026', 'UPI/DR/456/Shop', '-', '250.00', '-', '49,750.00'],
        ]
        txns = parse_table_rows([table_p1, table_p2])
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0]['description'], 'UPI/DR/123/Store')
        self.assertNotIn('Balance', txns[0]['description'])

    def test_is_likely_amount_token(self):
        self.assertTrue(is_likely_amount_token('171.00'))
        self.assertTrue(is_likely_amount_token('51,723.35'))
        self.assertTrue(is_likely_amount_token('1,000'))
        # Branch/PIN codes and raw integers should NOT be treated as amounts
        self.assertFalse(is_likely_amount_token('63970'))
        self.assertFalse(is_likely_amount_token('0097691162095'))
        self.assertFalse(is_likely_amount_token(''))

if __name__ == '__main__':
    unittest.main()