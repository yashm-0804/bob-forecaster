"""Physics assertions for the Holland wind field.

These check the shape of the field rather than exact values -- the exact
values get validated against CLIMADA's TropCyclone separately. What matters
here is that the profile peaks in the right place, decays outward, leans
right of track, and weakens over land.
"""

import numpy as np

from hazard.holland import (
    TrackPoint,
    gradient_wind,
    holland_b,
    land_decay,
    make_grid,
    swath,
    wind_field,
)


def montha() -> TrackPoint:
    """Cyclone Montha near landfall at Narasapuram, Oct 2025.

    IMD classified it a Severe Cyclonic Storm at ~95 km/h (26.4 m/s).
    """
    return TrackPoint(
        lat=16.45,
        lon=81.70,
        vmax_ms=26.4,
        pcen_hpa=990.0,
        rmax_km=50.0,
        trans_speed_ms=4.0,
        trans_dir_deg=315.0,
    )


def test_holland_b_within_physical_range():
    assert 1.0 <= holland_b(montha()) <= 2.5


def test_wind_peaks_near_radius_of_maximum_wind():
    point = montha()
    radii = np.linspace(1.0, 300.0, 600)
    profile = gradient_wind(point, radii)
    peak_radius = radii[int(np.argmax(profile))]
    # The peak should sit close to Rmax; Coriolis shifts it slightly outward.
    assert abs(peak_radius - point.rmax_km) < 10.0


def test_wind_decays_outward_beyond_rmax():
    point = montha()
    radii = np.array([60.0, 100.0, 200.0, 400.0])
    profile = gradient_wind(point, radii)
    assert np.all(np.diff(profile) < 0), "wind must fall monotonically outside Rmax"


def test_eye_is_calm_relative_to_eyewall():
    point = montha()
    eye = gradient_wind(point, np.array([1.0]))[0]
    eyewall = gradient_wind(point, np.array([point.rmax_km]))[0]
    assert eye < eyewall


def test_peak_wind_is_close_to_reported_vmax():
    """Holland's profile should reproduce roughly the storm's own vmax.

    Tolerance is wide because B is derived from the pressure deficit, which
    is only loosely consistent with vmax in real bulletins.
    """
    point = montha()
    peak = gradient_wind(point, np.linspace(1.0, 300.0, 600)).max()
    assert 0.6 * point.vmax_ms < peak < 1.6 * point.vmax_ms


def test_asymmetry_favours_right_of_track():
    """Northern-hemisphere storms are strongest right of the direction of travel."""
    point = montha()  # moving northwest (315 deg)
    lats, lons = make_grid(15.0, 18.0, 80.0, 83.5, 0.05)
    field = wind_field(point, lats, lons)

    # Right of a 315-degree heading is northeast; left is southwest.
    r_km = 80.0
    dlat = r_km / 111.0
    dlon = r_km / (111.0 * np.cos(np.radians(point.lat)))

    def sample(lat, lon):
        i = int(np.argmin(np.abs(lats[:, 0] - lat)))
        j = int(np.argmin(np.abs(lons[0, :] - lon)))
        return field[i, j]

    right = sample(point.lat + dlat * 0.7, point.lon + dlon * 0.7)
    left = sample(point.lat - dlat * 0.7, point.lon - dlon * 0.7)
    assert right > left


def test_land_decay_weakens_monotonically():
    assert land_decay(montha()) == 1.0
    inland = [
        land_decay(TrackPoint(16.0, 81.0, 26.4, 990.0, 50.0, hours_inland=h))
        for h in (0, 3, 6, 12, 24)
    ]
    assert inland == sorted(inland, reverse=True)
    assert inland[-1] < 0.2, "a storm 24 h inland should be much weakened"


def test_swath_is_running_maximum_over_track():
    """Every cell in the swath must be at least as strong as any single step."""
    track = [
        TrackPoint(15.5, 82.5, 26.4, 990.0, 50.0),
        TrackPoint(16.0, 82.0, 26.4, 988.0, 50.0),
        TrackPoint(16.45, 81.7, 25.0, 992.0, 55.0),
    ]
    lats, lons = make_grid(15.0, 17.5, 80.5, 83.5, 0.1)
    combined = swath(track, lats, lons)
    for point in track:
        assert np.all(combined >= wind_field(point, lats, lons) - 1e-9)


def test_stronger_pressure_deficit_gives_stronger_wind():
    weak = TrackPoint(16.0, 81.0, 26.4, 1000.0, 50.0)
    strong = TrackPoint(16.0, 81.0, 60.0, 940.0, 50.0)
    radii = np.linspace(1.0, 300.0, 300)
    assert gradient_wind(strong, radii).max() > gradient_wind(weak, radii).max()
