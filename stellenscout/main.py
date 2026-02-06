"""Main orchestrator for StellenScout CLI."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .cv_parser import extract_text
from .llm import create_client
from .search_agent import (
    profile_candidate,
    generate_search_queries,
    search_all_queries,
)
from .evaluator_agent import evaluate_all_jobs, filter_good_matches
from .models import EvaluatedJob
from .cache import ResultCache

# Load environment variables
load_dotenv()

console = Console()


def display_profile(profile) -> None:
    """Display the extracted candidate profile."""
    parts = []

    if profile.summary:
        parts.append(f"[italic]{profile.summary}[/italic]")
        parts.append("")

    parts.append(f"[bold]Experience:[/bold] {profile.experience_level} ({profile.years_of_experience} years)")
    parts.append(f"[bold]Target Roles:[/bold] {', '.join(profile.roles)}")
    parts.append(f"[bold]Skills:[/bold] {', '.join(profile.skills)}")
    parts.append(f"[bold]Languages:[/bold] {', '.join(profile.languages)}")
    parts.append(f"[bold]Domain Expertise:[/bold] {', '.join(profile.domain_expertise)}")

    if profile.education:
        parts.append(f"[bold]Education:[/bold] {', '.join(profile.education)}")
    if profile.certifications:
        parts.append(f"[bold]Certifications:[/bold] {', '.join(profile.certifications)}")

    profile_text = "\n".join(parts)

    panel = Panel(profile_text, title="📋 Candidate Profile", border_style="blue")
    console.print(panel)
    console.print()


def display_queries(queries: list[str]) -> None:
    """Display the generated search queries."""
    queries_text = "\n".join(f"  • {q}" for q in queries)
    panel = Panel(queries_text, title="🔍 Search Queries", border_style="green")
    console.print(panel)
    console.print()


def display_results(evaluated_jobs: list[EvaluatedJob], min_score: int) -> None:
    """Display the evaluation results in a table."""
    good_matches = filter_good_matches(evaluated_jobs, min_score)

    if not good_matches:
        console.print(
            f"[yellow]No jobs found with score >= {min_score}.[/yellow]"
        )
        console.print()

        # Show top 5 anyway
        if evaluated_jobs:
            console.print("[dim]Showing top 5 results regardless of score:[/dim]")
            good_matches = evaluated_jobs[:5]
        else:
            return

    table = Table(
        title=f"🎯 Job Matches (Score >= {min_score})",
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Score", justify="center", style="cyan", width=7)
    table.add_column("Title", style="white", max_width=35)
    table.add_column("Company", style="green", max_width=20)
    table.add_column("Location", style="yellow", max_width=15)
    table.add_column("Reasoning", style="dim", max_width=50)

    for ej in good_matches:
        score = ej.evaluation.score

        # Color code the score
        if score >= 80:
            score_str = f"[bold green]{score}[/bold green]"
        elif score >= 70:
            score_str = f"[yellow]{score}[/yellow]"
        else:
            score_str = f"[red]{score}[/red]"

        table.add_row(
            score_str,
            ej.job.title[:35],
            ej.job.company_name[:20],
            ej.job.location[:15],
            ej.evaluation.reasoning[:50] + "..." if len(ej.evaluation.reasoning) > 50 else ej.evaluation.reasoning,
        )

    console.print(table)
    console.print()

    # Print detailed view for top matches
    if good_matches:
        console.print("[bold]📝 Top Match Details:[/bold]")
        for i, ej in enumerate(good_matches[:3], 1):
            console.print(f"\n[bold cyan]{i}. {ej.job.title}[/bold cyan] at [green]{ej.job.company_name}[/green]")
            console.print(f"   Score: {ej.evaluation.score}/100")
            console.print(f"   Location: {ej.job.location}")
            console.print(f"   Reasoning: {ej.evaluation.reasoning}")
            if ej.evaluation.missing_skills:
                console.print(f"   Missing: {', '.join(ej.evaluation.missing_skills)}")
            if ej.job.link:
                console.print(f"   Link: {ej.job.link}")


def main() -> int:
    """Main entry point for StellenScout CLI."""
    parser = argparse.ArgumentParser(
        description="StellenScout: AI-powered job matching for the European market",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  stellenscout cv.pdf
  stellenscout cv.pdf --location "Munich, Germany"
  stellenscout cv.pdf --location "Paris, France"
  stellenscout cv.pdf --min-score 80 --jobs-per-query 10
  stellenscout cv.pdf --no-cache
        """,
    )

    parser.add_argument(
        "cv_path",
        type=Path,
        help="Path to your CV (supported: .pdf, .docx, .md, .txt)",
    )
    parser.add_argument(
        "--location", "-l",
        type=str,
        default="",
        help="Target job location (e.g., 'Munich, Germany', 'Paris, France')",
    )
    parser.add_argument(
        "--min-score", "-s",
        type=int,
        default=70,
        help="Minimum match score to display (default: 70)",
    )
    parser.add_argument(
        "--jobs-per-query", "-j",
        type=int,
        default=10,
        help="Number of jobs to fetch per search query (default: 10)",
    )
    parser.add_argument(
        "--num-queries",
        type=int,
        default=10,
        help="Number of search queries to generate (default: 10)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cache and force a fresh run",
    )

    args = parser.parse_args()

    cache = ResultCache() if not args.no_cache else None
    client = None  # lazy — create only when needed

    # Header
    console.print()
    console.print(
        Panel.fit(
            "[bold blue]StellenScout[/bold blue]\n"
            "[dim]AI-powered job matching for Europe[/dim]",
            border_style="blue",
        )
    )
    console.print()

    try:
        # Step 1: Parse CV
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Reading CV...", total=None)
            cv_text = extract_text(args.cv_path)
            progress.update(task, description="[green]✓[/green] CV loaded")

        # Step 2: Profile candidate
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            cached_profile = cache.load_profile(cv_text) if cache else None
            if cached_profile is not None:
                profile = cached_profile
                progress.add_task("[green]✓[/green] Profile extracted [dim][cached][/dim]", total=None)
            else:
                task = progress.add_task("Analyzing CV with AI...", total=None)
                client = create_client()
                profile = profile_candidate(client, cv_text)
                if cache:
                    cache.save_profile(cv_text, profile)
                progress.update(task, description="[green]✓[/green] Profile extracted")

        display_profile(profile)

        # Step 3: Generate search queries
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            cached_queries = cache.load_queries(profile, args.location) if cache else None
            if cached_queries is not None:
                queries = cached_queries
                progress.add_task("[green]✓[/green] Queries generated [dim][cached][/dim]", total=None)
            else:
                task = progress.add_task("Generating search queries...", total=None)
                if client is None:
                    client = create_client()
                queries = generate_search_queries(
                    client,
                    profile,
                    args.location,
                    num_queries=args.num_queries,
                )
                if cache:
                    cache.save_queries(profile, args.location, queries)
                progress.update(task, description="[green]✓[/green] Queries generated")

        display_queries(queries)

        # Step 4: Search for jobs
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            cached_jobs = cache.load_jobs() if cache else None
            if cached_jobs is not None:
                jobs = cached_jobs
                progress.add_task(
                    f"[green]✓[/green] Found {len(jobs)} unique jobs [dim][cached][/dim]",
                    total=None,
                )
            else:
                task = progress.add_task("Searching for jobs...", total=None)
                jobs = search_all_queries(queries, jobs_per_query=args.jobs_per_query, location=args.location)
                if cache:
                    cache.save_jobs(jobs)
                progress.update(
                    task,
                    description=f"[green]✓[/green] Found {len(jobs)} unique jobs"
                )

        if not jobs:
            console.print("[yellow]No jobs found. Try adjusting your search location.[/yellow]")
            return 1

        # Step 5: Evaluate jobs (only new ones)
        console.print()

        if cache:
            new_jobs, cached_evals = cache.get_unevaluated_jobs(jobs, profile)
        else:
            new_jobs, cached_evals = jobs, {}

        if not new_jobs:
            # Everything is cached
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task(
                    f"[green]✓[/green] All {len(cached_evals)} evaluations loaded [dim][cached][/dim]",
                    total=None,
                )
            all_evals = cached_evals
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                total_jobs = len(new_jobs)
                cached_count = len(cached_evals)
                label = f"Evaluating {total_jobs} new jobs"
                if cached_count:
                    label += f" ({cached_count} cached)"
                task = progress.add_task(f"{label}...", total=total_jobs)

                def update_progress(current, total):
                    progress.update(
                        task,
                        description=f"Evaluating job {current}/{total}...",
                        completed=current,
                    )

                if client is None:
                    client = create_client()
                new_evaluated = evaluate_all_jobs(
                    client, profile, new_jobs, progress_callback=update_progress
                )
                progress.update(task, description="[green]✓[/green] Evaluation complete")

            # Merge new evaluations into cached
            all_evals = dict(cached_evals)
            for ej in new_evaluated:
                key = f"{ej.job.title}|{ej.job.company_name}"
                all_evals[key] = ej

            if cache:
                cache.save_evaluations(profile, all_evals)

        # Build final sorted list
        evaluated_jobs = sorted(
            all_evals.values(),
            key=lambda x: x.evaluation.score,
            reverse=True,
        )

        console.print()

        # Step 6: Display results
        display_results(evaluated_jobs, args.min_score)

        return 0

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1
    except ValueError as e:
        console.print(f"[red]Configuration Error:[/red] {e}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        return 130


def cli():
    """CLI entry point."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
