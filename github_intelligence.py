#!/usr/bin/env python3
"""
GitHub Repo Hunter & Intelligence Engine
GitHub CLI (gh) ve GitHub REST API entegrasyonu ile gerçek kod içeren,
aktif ve yüksek kaliteli açık kaynak repoları arama ve inceleme motoru.
"""

import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional
import urllib.parse
import urllib.request


class GitHubIntelligence:
    """GitHub açık kaynak repo avcısı ve kod doğrulayıcı."""

    @classmethod
    def _get_auth_token(cls) -> Optional[str]:
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            return token
        try:
            gh_path = shutil.which("gh") or "/opt/homebrew/bin/gh"
            res = subprocess.run([gh_path, "auth", "token"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return None

    @classmethod
    def search_repos(cls, query: str, language: Optional[str] = None, min_stars: int = 1, limit: int = 5) -> Dict[str, Any]:
        """
        GitHub üzerinde belirtilen konuda ve dilde gerçek açık kaynak repoları arar.
        """
        q_raw = query.strip()
        detected_lang = language
        q_low = q_raw.lower()
        for lang_cand in ["python", "javascript", "typescript", "golang", "go", "rust", "solidity", "c++", "java", "php"]:
            if re.search(rf"\b{re.escape(lang_cand)}\b", q_low):
                detected_lang = detected_lang or ("go" if lang_cand == "golang" else lang_cand)
                q_raw = re.sub(rf"\b{re.escape(lang_cand)}\b", "", q_raw, flags=re.IGNORECASE)

        # Türkçe dolgu kelimelerini temizle
        clean_q = re.sub(r"\b(ile|yazılmış|olan|için|bir|ve|hakkında|örnek|uygulama|çalışan|açık|kaynak|kod|repo|proje)\b", "", q_raw, flags=re.IGNORECASE)
        clean_q = re.sub(r"\s+", " ", clean_q).strip()
        if not clean_q:
            clean_q = query.strip()

        gh_path = shutil.which("gh") or "/opt/homebrew/bin/gh"
        cmd = [gh_path, "search", "repos", clean_q, "--sort", "stars", "--limit", str(max(limit, 5)), "--json", "fullName,description,url,stargazersCount,updatedAt"]
        
        if detected_lang:
            cmd.extend(["--language", detected_lang])

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
            if res.returncode == 0:
                raw_items = json.loads(res.stdout)
                cleaned = []
                for item in raw_items:
                    stars = item.get("stargazersCount", 0)
                    if stars < min_stars and min_stars > 0:
                        continue
                    desc = (item.get("description") or "").strip()
                    cleaned.append({
                        "name": item.get("fullName"),
                        "url": item.get("url"),
                        "stars": stars,
                        "description": desc or "Açıklama belirtilmemiş.",
                        "updated_at": (item.get("updatedAt") or "")[:10]
                    })
                return {
                    "success": True,
                    "query": query,
                    "count": len(cleaned),
                    "repositories": cleaned[:limit]
                }
        except Exception as exc:
            pass

        # Fallback: GitHub REST API
        try:
            q = query
            if language:
                q += f" language:{language}"
            if min_stars > 0:
                q += f" stars:>={min_stars}"
            encoded_q = urllib.parse.quote(q)
            api_url = f"https://api.github.com/search/repositories?q={encoded_q}&sort=stars&order=desc&per_page={limit}"
            
            headers = {"User-Agent": "BarisAI-Intelligence/1.0", "Accept": "application/vnd.github.v3+json"}
            token = cls._get_auth_token()
            if token:
                headers["Authorization"] = f"token {token}"

            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                cleaned = []
                for item in items:
                    cleaned.append({
                        "name": item.get("full_name"),
                        "url": item.get("html_url"),
                        "stars": item.get("stargazers_count", 0),
                        "description": item.get("description") or "Açıklama belirtilmemiş.",
                        "updated_at": (item.get("updated_at") or "")[:10],
                        "language": item.get("language")
                    })
                return {
                    "success": True,
                    "query": query,
                    "count": len(cleaned),
                    "repositories": cleaned
                }
        except Exception as exc:
            return {"success": False, "error": f"GitHub araması başarısız: {str(exc)}", "repositories": []}

    @classmethod
    def inspect_repo_contents(cls, repo_full_name: str, path: str = "") -> Dict[str, Any]:
        """
        Belirtilen reponun içeriğini inceler; gerçek kod dosyalarının varlığını kanıtlar.
        """
        gh_path = shutil.which("gh") or "/opt/homebrew/bin/gh"
        api_endpoint = f"repos/{repo_full_name}/contents/{path}".strip("/")
        try:
            res = subprocess.run([gh_path, "api", api_endpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if res.returncode == 0:
                items = json.loads(res.stdout)
                if isinstance(items, list):
                    files = [{"name": i.get("name"), "type": i.get("type"), "size": i.get("size", 0), "path": i.get("path")} for i in items[:25]]
                    code_files = [f["name"] for f in files if any(f["name"].endswith(ext) for ext in [".py", ".js", ".ts", ".go", ".rs", ".cpp", ".c", ".java", ".php", ".sh"])]
                    has_package_spec = any(f["name"] in {"setup.py", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements.txt", "Makefile"} for f in files)
                    has_src_dir = any(f["type"] == "dir" and f["name"] in {"src", "lib", "app", "cmd", "pkg", repo_full_name.split("/")[-1].lower()} for f in files)
                    has_real_code = len(code_files) > 0 or has_package_spec or has_src_dir
                    return {
                        "success": True,
                        "repo": repo_full_name,
                        "total_items": len(items),
                        "has_code": has_real_code,
                        "code_files": code_files,
                        "has_package_spec": has_package_spec,
                        "files": [f["name"] for f in files]
                    }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        return {"success": False, "error": "Repo içerikleri alınamadı."}
