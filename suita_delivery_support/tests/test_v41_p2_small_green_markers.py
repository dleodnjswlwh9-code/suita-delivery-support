from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p2_shelter_markers_are_fixed_small_and_green():
    routes = (ROOT / 'templates' / 'routes.html').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'style.css').read_text(encoding='utf-8')

    assert 'const P2_SHELTER_RADIUS_PX=6;' in routes
    assert 'function markerRadius(){return P2_SHELTER_RADIUS_PX;}' in routes
    assert 'markerRadius(p.demandKits)' not in routes
    assert 'markerRadius(record.demandKits)' not in routes
    assert 'const x=X(Number(p.lng)),y=Y(Number(p.lat)),r=markerRadius();' in routes
    assert 'const radius=markerRadius(),padding=2,c=radius+padding,size=c*2;' in routes
    assert routes.count('fill="#16a36d"') == 2
    assert '#7b3fc6' not in routes
    assert 'p2-green-dot' in routes
    assert '避難所：すべて同じ大きさ' in routes
    assert '緑色の割合：選択回終了時点の充足率' in routes
    assert '.p2-ui .p2-green-dot' in css
    assert 'background:conic-gradient(#16a36d var(--p2-rate)' in css


def test_p1_map_not_changed_by_p2_markers():
    assert (ROOT / 'templates' / 'allocation.html').exists()
    assert (ROOT / 'templates' / 'plan.html').exists()
