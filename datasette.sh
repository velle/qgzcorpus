echo "Open in browser: http://localhost:8001/static/index.html"
datasette corpus.db --static static:./static --cors
