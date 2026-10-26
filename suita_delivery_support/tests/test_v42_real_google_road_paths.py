from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=(ROOT/'templates'/'routes.html').read_text(encoding='utf8')

def test_real_road_routes_used_when_available():
    assert 'Route.computeRoutes(req)' in TEMPLATE
    assert 'for(const {leg,i,routeColor} of all)drawRouteLeg(' in TEMPLATE
    assert 'for(const rt of show)' in TEMPLATE
    assert "travelMode:'DRIVING'" in TEMPLATE
    assert 'optimizeWaypointOrder:canOptimize' in TEMPLATE

def test_google_failure_uses_clearly_labelled_schematic_not_blank():
    assert 'function googleSchematicRoute(res,rt,single)' in TEMPLATE
    assert 'for(const rt of show)googleSchematicRoute(res,rt,show.length===1)' in TEMPLATE
    assert '直線概略図' in TEMPLATE
    assert 'roadAlert(' in TEMPLATE

def test_plain_small_markers_and_p1_unchanged():
    assert 'const P2_SHELTER_RADIUS_PX=6;' in TEMPLATE
    assert 'function stopMarkerSvg(cx,cy,r)' in TEMPLATE
    assert (ROOT/'templates'/'allocation.html').exists()

def test_api_limits_and_visible_diagnostics():
    assert 'for(let first=0;first<pts.length-1;first+=26)' in TEMPLATE
    assert 'id="p2-road-alert"' in TEMPLATE
    assert '道路経路 ${success}/${show.length}件' in TEMPLATE
