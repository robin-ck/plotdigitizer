"""Spec parser on hand-built drawing dicts mimicking journal path topologies."""

from pymupdf import Point, Quad, Rect

from plotdigitizer.vector import collect, markers_of


def L(a, b):
    return ("l", Point(*a), Point(*b))


def C(p0, p1, p2, p3):
    return ("c", Point(*p0), Point(*p1), Point(*p2), Point(*p3))


def drawing(items, typ="s", rect=None):
    xs = [p.x for it in items for p in it[1:] if isinstance(p, Point)]
    ys = [p.y for it in items for p in it[1:] if isinstance(p, Point)]
    for it in items:
        if it[0] == "re":
            xs += [it[1].x0, it[1].x1]
            ys += [it[1].y0, it[1].y1]
        if it[0] == "qu":
            xs += [it[1].ul.x, it[1].lr.x, it[1].ur.x, it[1].ll.x]
            ys += [it[1].ul.y, it[1].lr.y, it[1].ur.y, it[1].ll.y]
    return {"items": items, "type": typ, "rect": rect or Rect(min(xs), min(ys), max(xs), max(ys)),
            "color": (0, 0, 0), "fill": (0, 0, 0) if "f" in typ else None}


def rays(c, dirs, r=2.0):
    return [L(c, (c[0] + a * r, c[1] + b * r)) for a, b in dirs]


def circle(cx, cy, r=2.0, n=4):
    import math
    k = 4 / 3 * math.tan(math.pi / (2 * n)) * r
    items = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        p1 = (p0[0] - k * math.sin(a0), p0[1] + k * math.cos(a0))
        p2 = (p3[0] + k * math.sin(a1), p3[1] - k * math.cos(a1))
        items.append(C(p0, p1, p2, p3))
    return items


def shapes(ms):
    return [(m[0], round(m[1], 2), round(m[2], 2)) for m in ms]


def test_rays_x_plus_star():
    X = [(1, 1), (-1, -1), (1, -1), (-1, 1)]
    P = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    S = X + [(-1, 0), (1, 0)]
    d = drawing(rays((10, 10), X) + rays((20, 10), P) + rays((30, 10), S))
    assert shapes(markers_of(d)) == [("x", 10, 10), ("plus", 20, 10), ("star", 30, 10)]


def test_closed_chains_triangle_rotated_and_diamond():
    tri_up = [L((0, 2), (2, -2)), L((2, -2), (-2, -2)), L((-2, -2), (0, 2))]
    tri_rot = [L((8, -2), (12, 0)), L((12, 0), (8, 2)), L((8, 2), (8, -2))]
    dia = [L((20, -2), (22, 0)), L((22, 0), (20, 2)), L((20, 2), (18, 0)), L((18, 0), (20, -2))]
    ms = markers_of(drawing(tri_up + tri_rot + dia))
    assert [m[0] for m in ms] == ["tri", "tri", "dia"]
    assert (round(ms[1][1], 2), round(ms[1][2], 2)) == (10, 0)


def test_re_qu_circle():
    d = drawing([("re", Rect(0, 0, 4, 4)), ("qu", Quad(Point(10, 0), Point(12, 2), Point(8, 2), Point(10, 4)))]
                + circle(20, 2) + circle(30, 2))
    assert shapes(markers_of(d)) == [("sq", 2, 2), ("dia", 10, 2), ("circ", 20, 2), ("circ", 30, 2)]


def test_eight_curve_circle_is_one_marker():
    ms = markers_of(drawing(circle(5, 5, n=8)))
    assert shapes(ms) == [("circ", 5, 5)]


def test_size_limit_rejects_large_chain():
    big = [L((0, 0), (10, 0)), L((10, 0), (5, 8)), L((5, 8), (0, 0))]
    assert markers_of(drawing(big)) == []


def test_polyline_is_not_marker():
    poly = [L((i, i * 0.5), (i + 1, (i + 1) * 0.5)) for i in range(6)]
    assert markers_of(drawing(poly)) == []


def test_fill_then_stroke_pair_is_one_filled_marker():
    f = drawing(circle(10, 10) + circle(20, 10), "f")
    s = drawing(circle(10, 10) + circle(20, 10), "s")
    ms = collect([f, s], (0, 0, 40, 40))
    assert len(ms) == 2 and all(m["filled"] for m in ms)


def test_stroke_after_fill_at_other_positions_is_kept():
    f = drawing(circle(10, 10), "f")
    s = drawing(circle(30, 10), "s")
    ms = collect([f, s], (0, 0, 40, 40))
    assert [m["filled"] for m in ms] == [True, False]


def test_several_series_in_one_path_same_position():
    # triangle and x at the same centre in ONE path: grouped sequentially
    tri = [L((-2, 2), (2, 2)), L((2, 2), (0, -2)), L((0, -2), (-2, 2))]
    x = rays((0, 0), [(1, 1), (-1, -1), (1, -1), (-1, 1)])
    ms = markers_of(drawing(tri + x + tri))
    assert [m[0] for m in ms] == ["tri", "x", "tri"]
    assert all(abs(m[1]) < 1e-9 for m in ms)


def test_matplotlib_style_x_and_plus():
    x = [L((-2, -2), (2, 2)), L((-2, 2), (2, -2))]
    p = [L((8, 0), (12, 0)), L((10, -2), (10, 2))]
    assert [m[0] for m in markers_of(drawing(x))] == ["x"]
    assert [m[0] for m in markers_of(drawing(p))] == ["plus"]
