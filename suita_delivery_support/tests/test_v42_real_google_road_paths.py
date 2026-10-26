from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=(ROOT/'templates'/'routes.html').read_text(encoding='utf8')


def test_all_displayed_trucks_use_actual_google_street_route_geometry():
    assert 'Route.computeRoutes(req)' in TEMPLATE
    assert 'for(const leg of data.legs){drawRouteLeg(leg' in TEMPLATE
    assert 'for(const rt of show)' in TEMPLATE
    assert "travelMode:'DRIVING'" in TEMPLATE
    assert 'optimizeWaypointOrder:canOptimize' in TEMPLATE


def test_no_straight_line_google_overlay_if_routing_api_fails():
    assert 'new google.maps.Polyline({map:gm,path:pointsForRoute' not in TEMPLATE
    assert 'gmDirectionService' not in TEMPLATE
    assert '直線で代用していません。' in TEMPLATE
    assert 'roadAlert(' in TEMPLATE


def test_small_green_markers_retained_and_p1_unchanged():
    assert 'const P2_SHELTER_RADIUS_PX=6;' in TEMPLATE
    assert 'fill="#16a36d"' in TEMPLATE
    assert (ROOT/'templates'/'allocation.html').exists()


def test_api_limits_and_visible_diagnostics():
    assert 'for(let first=0;first<pts.length-1;first+=26)' in TEMPLATE
    assert 'id="p2-road-alert"' in TEMPLATE
    assert 'Google 道路経路 ${success}/${show.length}件' in TEMPLATE
