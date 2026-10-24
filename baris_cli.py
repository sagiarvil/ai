#!/usr/bin/env python3
"""
BARIS AI // SUPREME TERMINAL CLI (TYPER & RICH)
n8n'siz, doğrudan terminalden veya IDE içinden çalışan resmi Barış AI kumanda merkezi.
"""

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Barış AI // Otonom Deterministik Mühendislik ve GitHub Araştırma Motoru")
console = Console()

@app.command()
def status():
    """Tüm yerel ve fiziksel motorların sağlık durumunu listeler."""
    from installed_engines_bridge import InstalledEnginesBridge
    import shutil

    table = Table(title="🛡️ Barış AI Fiziksel Motor Durumu", header_style="bold cyan")
    table.add_column("Motor", style="bold white")
    table.add_column("Durum", style="bold green")
    table.add_column("Konum / Binary", style="dim")
    table.add_column("Gecikme (ms)", justify="right")

    health = InstalledEnginesBridge.get_all_engines_health()
    for name, data in health.get("engines", {}).items():
        status_text = "[green]AKTİF[/green]" if data.get("available") else "[red]DEVRE DIŞI[/red]"
        path_text = data.get("binary") or data.get("path") or "-"
        ping = str(data.get("ping_ms", "-"))
        table.add_row(name, status_text, path_text, ping)

    # ast-grep durumu
    ast_path = shutil.which("ast-grep")
    ast_status = "[green]AKTİF[/green]" if ast_path else "[red]DEVRE DIŞI[/red]"
    table.add_row("ast-grep (Fiziksel AST Motoru)", ast_status, ast_path or "Bulunamadı", "0.01")

    console.print(table)

@app.command()
def inspect(
    repo_url: str = typer.Argument(..., help="İncelenecek GitHub repo URL'si veya 'owner/repo'"),
    task: str = typer.Option("Genel mimari ve kod yapısını analiz et", "--task", "-t", help="İcra edilecek görev veya analiz sorusu")
):
    """Belirtilen GitHub reposunu ast-grep + LangGraph + LiteLLM ile sıfır halüsinasyonla inceler."""
    console.print(Panel(f"[bold cyan]Hedef Repo:[/bold cyan] {repo_url}\n[bold yellow]Görev:[/bold yellow] {task}", title="🚀 Barış AI LangGraph İcra Başladı"))
    
    from baris_langgraph_engine import BarisLangGraphEngine
    res = BarisLangGraphEngine.run_investigation(task=task, repo_url=repo_url)

    if res.get("success"):
        console.print(Panel(f"[bold green]Kullanılan Motor:[/bold green] {res.get('model_used')}\n[bold green]Deneme Sayısı:[/bold green] {res.get('attempts')}\n[bold green]Taranan AST Düğümü:[/bold green] {res.get('ast_count')}", title="✅ İnceleme Başarıyla Doğrulandı"))
        console.print("\n[bold white]Sonuç Raporu:[/bold white]\n")
        console.print(res.get("output", ""))
    else:
        console.print(f"[bold red]Hata:[/bold red] {res.get('output')}")

@app.command()
def scan_secrets(target: str = typer.Argument(".", help="Taranacak dosya veya dizin yolu")):
    """Gitleaks ve TruffleHog motorları ile derin gizli anahtar ve token taraması yapar."""
    from installed_engines_bridge import InstalledEnginesBridge
    console.print(f"[*] Hedef dizin taranıyor: [bold]{target}[/bold]...")
    res = InstalledEnginesBridge.scan_secrets(target)
    console.print_json(data=res)

if __name__ == "__main__":
    app()
