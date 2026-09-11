from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def RootTest():
    return {"message": "I am groot."}

