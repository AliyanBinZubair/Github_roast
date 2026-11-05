from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from google import genai
import os, html, httpx, markdown

load_dotenv()
BASE = os.getenv("BASE_URL","http://localhost:8000")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
models = []

# taking available models
for model in client.models.list():
    models.append(model.name)  # append the present models


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("github_roast_cookie"), https_only=BASE.startswith("https"))
# the cookies set from SessionMiddleware have default expiry time of 14 days

oauth = OAuth()
oauth.register(
    name="github",
    client_id=os.getenv("Github_client_id"),
    client_secret=os.getenv("Github_secret"),
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    access_token_url="https://github.com/login/oauth/access_token",
    redirect_url=f"{BASE}/callback",
    client_kwargs={"scope":"read:user user:email, repo"},
)

PAGE = """
<html>
    <head>
        <title>Your Github Roast</title>
        <style> body{font-size: 15px; line-height:1; font-style:sans-sarif;} </style>
    </head>
    <body>__BODY__</body>
</html>
"""



@app.get("/")
def home(request:Request):
    user = request.session.get("user")
    if user and isinstance(user,dict) and user.get("email"):   #isinstance verify if user is dict or not (isinstance(object,type))
        email = html.escape(user["email"])  # we use it so that email dont treat as code
        body=f"""
        <h1>Github Roast!</h1>
        <p>Loged in as {email}</p>
        <a href='/roast'>Roast</a><br>
        <a href='/logout'>Logout</a>
        """
    else:
        body = f"""
        <h1>Github Roast</h1>
        <a href='/login'>Login</a>
        """
    return HTMLResponse(PAGE.replace("__BODY__",body))

@app.get("/login")
async def login(request:Request):
    redirect_url = f"{BASE}/callback"
    return await oauth.github.authorize_redirect(request,redirect_url,prompt="select_account") # attach state to request and redirect to redirect_url after login with google is done
    
@app.get("/callback")
async def callback(request: Request):
    try:
        token = await oauth.github.authorize_access_token(request)
    except Exception as e :
        print(f"print from the Expection section: {e}")
        return RedirectResponse("/")
    

    res = await oauth.github.get("user" , token=token) # token=token is same as header{Authorization: Bearer token["access_token"]}
    userinfo = res.json()                              # but authlib requires token=token and above method is invalid for it
    email = userinfo.get("email")
    
    if not email:
        res = await oauth.github.get("user/emails", token=token)
        emails = res.json()
        
        primary = next((e for e in emails if e.get("primary")), None) # get the first primary email
        email = primary["email"] if primary else None   # if primary is not empty then asign this email to email
    
    if email:
        request.session["user"] = {"email": email}
        request.session["token"] = token # stores the whole dict so later i can do token=token
    else:
        print("Authorizaiton succeeded ,but no email was fount!")
    
    return RedirectResponse("/") # It redirect it to "/" path
    
@app.get("/logout") 
def logout(request:Request):
    request.session.clear()
    return RedirectResponse("/")
    
@app.get("/roast")
async def roast(request:Request):
    user = request.session.get("user")
    token = request.session.get("token")
    if user and token:
        try:
            res = await oauth.github.get("user/repos",params={"per_page":100,"type":"all"}, token=token)
            
            # Parameter,    Possible values,                              What it controls
            # per_page,     1–100 (default 30),                           How many repos in one response
            # page,         "1, 2, 3…",                                   Which page (for pagination)
            # sort,         "created, updated,                            pushed, full_name",Order of the list
            # direction,    asc / desc,                                   Ascending or descending
            # type,         "all, owner, public, private, member",        Which repos to return
            # visibility,   "all, public, private",                       Same idea as type (slightly different filter)
            # affiliation,  "owner, collaborator, organization_member",   Who you are related to the repo
            
        except Exception as e:
            print(f"Expetion from /roast :{e}")
            return RedirectResponse("/")
        
        if res.status_code == 401:
            print(f"token expired!. login again")
            request.session.clear()
            return RedirectResponse("/login")

        user_repos = res.json()
        useful_data = [{"name":repo.get("full_name"),
                           "stars": repo.get("stargazers_count"),
                           "description":repo.get("description") or "No description",# "or" check from left to right and returns frist true value , 
                           "language":repo.get("language") or "No langauge detected",  #"and" checks from left to right and return first falsy value and if all true then returns right value
                           "last_push":repo.get("pushed_at"),
                           "forsks":repo.get("forks_count"),
                           "size_kb":repo.get("size"),
                           "is_fork":repo.get("fork"),
                           "topics":repo.get("topics",[])}
                          for repo in user_repos]
            
        prompt = f"""
        You are a savage but funny GitHub roaster.
        Roast this developer based on their repositories.
        Be witty, sarcastic, and a bit mean — but still keep it light-hearted.
        Don't just list the repos. Make fun of patterns, abandoned projects, zero stars, bad naming, etc.

        Here is the data:
        {useful_data}
        """
        roast_text = ""
        for model in models[:15]:   #top 15 models
            try:
                gemini_response = client.models.generate_content(model=model, contents=prompt)  # gemini response is not a dict or list , its a specific class so that's why we can use .text here
                roast_text = gemini_response.text # .text extract the main text from useless informations like usage metadata, candidates, etc
                break
            except Exception as e:
                print(f"Exception from gemini {model} response loop : {e}")
        
        roast = markdown.markdown(html.escape(roast_text, quote=False))  # quote=False means leave "" 
        return HTMLResponse(PAGE.replace("__BODY__",roast))
    else:
        request.session.clear()
        return RedirectResponse("/")