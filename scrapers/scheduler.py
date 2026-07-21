from __future__ import annotations

import argparse
import asyncio
import json

from scrapers.core.scheduler import list_schedules, run_due_once, run_manual_job, run_scheduler_forever


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dedicated sale scraping scheduler")
    parser.add_argument("--list-schedules", action="store_true", help="Print registered schedules and exit")
    parser.add_argument("--run-due-once", action="store_true", help="Run currently due schedules once and exit")
    parser.add_argument("--provider", help="Provider key for a single manual job")
    parser.add_argument(
        "--job-type",
        choices=["sale_health_check", "sale_priority_crawl", "sale_full_crawl"],
        help="Run one scheduler job and exit",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse without persisting crawl changes")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional development cap for listing pages")
    parser.add_argument("--max-details", type=int, default=None, help="Optional development cap for detail pages")
    args = parser.parse_args()

    async def _run() -> object:
        if args.list_schedules:
            return await list_schedules()
        if args.run_due_once:
            return await run_due_once()
        if args.provider or args.job_type:
            if not args.provider or not args.job_type:
                raise SystemExit("--provider and --job-type must be used together")
            return await run_manual_job(
                provider_key=args.provider,
                job_type=args.job_type,
                dry_run=args.dry_run,
                max_pages=args.max_pages,
                max_details=args.max_details,
            )
        await run_scheduler_forever()
        return None

    result = asyncio.run(_run())
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
