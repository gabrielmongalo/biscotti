"""
biscotti._user_source
~~~~~~~~~~~~~~~~~~~~~
Entry point for `biscotti dev` in user project mode.
Created when biscotti_config.py is detected.
"""
from fastapi import FastAPI
from biscotti import Biscotti

bi = Biscotti(storage="biscotti.db")

app = FastAPI(title="biscotti")
app.mount("/biscotti", bi.app)


@app.get("/")
async def root():
    return {"message": "biscotti", "ui": "/biscotti"}
