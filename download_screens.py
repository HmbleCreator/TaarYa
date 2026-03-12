"""Download all Stitch screen HTML files."""
import urllib.request
import os

screens = {
    "static/kg_explorer_1.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzUxYTQ2MWRkN2JhZTQyZjA5ZmNkZDMyZGIyYTJkZjNjEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_2.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzBlNDgxNGQxNGJhMjQ2NjE4MGMyNDQ3Njg5NTljY2EwEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_3.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2YyZWJjOWUwYzQzZTRkNzM4ZTIxNzZjMDY5NjUxMjZjEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_4.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzE0YzEwY2I1YWZkMDRhNWE4NTRiM2Q1OTIxZTNhYTQwEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_5.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2ZhZmIyMzY1YWQyNTQ3MWJiZTI2NDEyZDg2Y2UzNzFiEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_6.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzMwZmZhOGQ5NWFjZDQwNmE5NWJiNzQ5YWNhYWQxZmFiEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_7.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2UyMGU2NmRhZjEwZTRjOTM5YzU1NjdjMmM5NjdkNzAzEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_8.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2M1MmNlOGNiMTc2YzQyMDFiNzc5Yzc0ZDE3YTM0YjcxEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_9.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzQ5ODc0NWU3MTdlNzQ3Y2JhYTQ1YmJhNDNiNWE1Yjc0EgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_explorer_10.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzI2ZjRjOTRlMTQ2YTQ1MWViNTNjYTZjZDI0MTgxMTk5EgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/kg_light.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzU0YWMxODBkMDJhODQzYjI4ZjhjNTU1NmY0MTVkNjRmEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/analysis_console.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzI2MDJhYzkzZGEzMjQ0YTliNGZlNTBmMDA2NzQyOTM3EgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/onboarding1.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2I4OTRjMDljZmIwYjRkMDM4YTlkMWQyZmQzZTQ3Y2YyEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/onboarding2.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2QzYzVjY2QzN2E4MTQwZjhhZTIwOTI5N2I5ODJjMGQwEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/onboarding3.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sXzlmNjMwYjg4ZmI0ODQzY2ZhZjVlZDE2MTA3MTMzN2MyEgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/profile_dark.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2I2ZGE2NzI1Y2Q1MDQ5ZWY4MTc0Nzk2Y2UzN2UwZWQ1EgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
    "static/profile_light.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ8Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpbCiVodG1sX2E4NTk0ZGQyZmU3NTRiODRhYWFiZDg5NjE1OWJhYjU0EgsSBxCt0YbvkB8YAZIBJAoKcHJvamVjdF9pZBIWQhQxMzM3OTAzNzk4MjYxMTEwNjk2MA&filename=&opi=89354086",
}

headers = {"User-Agent": "Mozilla/5.0"}

for filename, url in screens.items():
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "wb") as f:
            f.write(content)
        print(f"OK  {filename} ({len(content)} bytes)")
    except Exception as e:
        print(f"ERR {filename}: {e}")

print("Done.")
