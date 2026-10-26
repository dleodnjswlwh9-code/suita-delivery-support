from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_p2_shelter_markers_are_fixed_small_plain_dots():
    routes=(ROOT/'templates'/'routes.html').read_text(encoding='utf8')
    assert 'const P2_SHELTER_RADIUS_PX=6;' in routes
    assert 'function markerRadius(){return P2_SHELTER_RADIUS_PX;}' in routes
    assert 'markerRadius(p.demandKits)' not in routes
    assert 'markerRadius(record.demandKits)' not in routes
    assert 'function stopMarkerSvg(cx,cy,r)' in routes
    assert 'stopMarkerSvg(x,y,r)' in routes
    assert 'stopMarkerSvg(c,c,radius)' in routes
    assert 'pieSvg(' not in routes

def test_p1_map_not_changed_by_p2_markers():
    assert (ROOT/'templates'/'allocation.html').exists()
    assert (ROOT/'templates'/'plan.html').exists()
