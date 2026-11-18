"""Command line interface.

    plotdigitizer list-figures <pdf>
    plotdigitizer digitize <pdf> --card figure_card.json [--out out]
    plotdigitizer reimport <corrected_wpd.json|.tar> <figdir> [--panel b]
    plotdigitizer collect <out>
    plotdigitizer serve [--host 127.0.0.1] [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="plotdigitizer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("list-figures", help="stage 1: list figures (captions + graphics clusters)")
    a.add_argument("pdf")
    a.add_argument("--json", action="store_true")

    d = sub.add_parser("digitize", help="extract one figure described by a Figure Card")
    d.add_argument("pdf")
    d.add_argument("--card", required=True, help="hand-written Figure Card (JSON)")
    d.add_argument("--out", default="out")

    r = sub.add_parser("reimport", help="re-import a corrected WebPlotDigitizer project")
    r.add_argument("project")
    r.add_argument("figdir")
    r.add_argument("--panel")

    c = sub.add_parser("collect", help="combine all points.csv into one CSV")
    c.add_argument("out")

    w = sub.add_parser("serve", help="run the web interface (needs the 'web' extra)")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("plotdigitizer.web.app:app", host=args.host, port=args.port, proxy_headers=False)
        return 0
    if args.cmd == "list-figures":
        from .find_figures import find_figures
        figs = find_figures(args.pdf)
        if args.json:
            print(json.dumps(figs, indent=2, ensure_ascii=False))
        else:
            for f in figs:
                print(f"Fig. {f['number']:>3}  page {f['page_pdf']:>3}  {f['kind']:<6}"
                      f"{' (mixed)' if f['mixed'] else ''}  bbox={f['bbox']}  {f['caption'][:70]}")
        return 0
    if args.cmd == "digitize":
        from .figure_card import load_card
        from .pipeline import digitize
        res = digitize(args.pdf, load_card(args.card), args.out)
        _report(res)
        print(f"output: {res['outdir']}")
        return 1 if res["errors"] else 0
    if args.cmd == "reimport":
        from .pipeline import reimport
        res = reimport(args.project, args.figdir, args.panel)
        print("changes:", res["stats"])
        _report(res)
        return 1 if res["errors"] else 0
    if args.cmd == "collect":
        from .export import collect_csv
        print(collect_csv(args.out))
        return 0
    return 2


def _report(res):
    print(f"points: {len(res['rows'])}")
    for c in res["checks"]:
        if not c["ok"]:
            print(f"  [{c['level']}] {c['check']}: {json.dumps(c['detail'], ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    sys.exit(main())
