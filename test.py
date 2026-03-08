from app import NewsService, CACHE_PATH, render_page

service = NewsService(CACHE_PATH)
html = render_page(service)
assert "每日 AI 新聞" in html
print("Smoke test passed")
