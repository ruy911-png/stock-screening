import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from blacklist import build, classify


class BlacklistTest(unittest.TestCase):
    def test_persistence_and_boundary(self):
        self.assertEqual(classify({'valid':120,'rate':.15},{'valid':120,'rate':.15}),'blacklist')
        self.assertEqual(classify({'valid':120,'rate':.15},{'valid':120,'rate':.10}),'watch')
        self.assertEqual(classify({'valid':120,'rate':.14},{'valid':120,'rate':.20}),'not_flagged')

    def test_insufficient_data_is_not_clean(self):
        self.assertEqual(classify({'valid':99,'rate':.20},{'valid':120,'rate':.20}),'insufficient_data')

    def test_appending_future_bars_does_not_change_past_list(self):
        start=date(2024,1,1)
        values=[]
        for i in range(240):
            d=(start+timedelta(days=i)).strftime('%Y%m%d')
            values.append(f'<item data="{d}|100|102|99.8|100.1|100"/>')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            path=folder/'298040.xml'
            path.write_text('<root>'+''.join(values)+'</root>')
            asof=(start+timedelta(days=239)).isoformat()
            before=build(folder,asof)
            future='<item data="20261231|500|501|100|110|1000"/>'
            path.write_text('<root>'+''.join(values)+future+'</root>')
            self.assertEqual(before,build(folder,asof))


if __name__ == '__main__':
    unittest.main()
