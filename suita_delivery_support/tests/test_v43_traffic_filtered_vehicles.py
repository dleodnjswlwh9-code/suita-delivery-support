from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'templates'/'routes.html').read_text(encoding='utf8')


def test_selected_vehicle_limits_shelter_markers_in_both_maps():
    assert 'function displayedShelterIndexes(res,show)' in HTML
    assert "return new Set(show.flatMap(rt=>rt.stops.map(stop=>stop.index)))" in HTML
    assert 'for(const record of displayed)' in HTML
    assert 'const dots=subset.map(p=>' in HTML
    assert 'const hubsToDraw' not in HTML  # hub selection is scoped in fallbackDiagram
    assert 'hubsToDraw=show.length===1?' in HTML


def test_table_and_p2_markers_are_filter_consistent():
    assert 'function displayedSnapshotRows(res,show)' in HTML
    assert 'const snap=roundSnapshot(res),show=selectedRoutes(res),shown=displayedSnapshotRows(res,show);' in HTML
    assert 'shown.map((s,i)=>' in HTML
    assert '選択回終了時点の値です' in HTML


def test_google_routing_has_live_traffic_aware_and_eta_fields():
    assert "routingPreference:'TRAFFIC_AWARE'" in HTML
    assert "fields:['path','legs','durationMillis','distanceMeters','optimizedIntermediateWaypointIndices']" in HTML
    assert 'const t=Number(chosen.durationMillis)' in HTML
    assert '30+15*rt.stops.length+0.04*rt.kits' in HTML
    assert 'f2+=Math.max(0,...times)' in HTML


def test_no_false_live_traffic_claim_on_partial_api_failures():
    assert 'const complete=ready===total && total>0;' in HTML
    assert 'if(complete){' in HTML
    assert '暫定値：市街地距離÷20km/h' in HTML
    assert 'F2は暫定値のままです。' in HTML


def test_traffic_layer_is_separate_and_optional():
    assert "new google.maps.TrafficLayer({autoRefresh:true})" in HTML
    assert 'id="p2-traffic-layer"' in HTML
    assert "$('p2-refresh-traffic').addEventListener('click'" in HTML


def test_results_page_uses_only_fresh_matching_google_traffic_data():
    results=(ROOT/'templates'/'results.html').read_text(encoding='utf8')
    assert "saved.traffic" in results
    assert 'Date.now()-Date.parse(traffic.evaluatedAt)<10*60*1000' in results
    assert 'traffic.signature===trafficSignature(r)' in results
    assert "live?traffic.f2Minutes:r.f2Minutes" in results
    assert "trafficPlanSignature(res)" in HTML
    assert "stored.traffic={source:'google-traffic-aware'" in HTML
