#!/bin/sh
set -eu

PORT="${PORT:-8787}"
UKUMOG_HOST="${UKUMOG_HOST:-127.0.0.1}"
UKUMOG_PORT="${UKUMOG_PORT:-8011}"

node -e "const http=require('http');const req=http.get({host:'127.0.0.1',port:process.env.PORT||8787,path:'/health'},res=>process.exit(res.statusCode===200?0:1));req.on('error',()=>process.exit(1));req.setTimeout(3000,()=>{req.destroy();process.exit(1);});"
python -c "import os, sys, urllib.request; host=os.environ.get('UKUMOG_HOST','127.0.0.1'); port=os.environ.get('UKUMOG_PORT','8011'); url=f'http://{host}:{port}/health';\
resp=urllib.request.urlopen(url, timeout=3); sys.exit(0 if resp.status == 200 else 1)"
