from flask import (Flask,
                   render_template,
                   request,
                   redirect,
                   jsonify,
                   url_for,
                   flash,
                   make_response)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from models import Base, Spirit, Recipe, User
from flask import session as login_session
import random, string, httplib2, json, requests, os, sys
from oauth2client.client import flow_from_clientsecrets, FlowExchangeError


app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'drinkcatalog.db')
CLIENT_SECRETS_JSON_PATH = os.path.join(BASE_DIR, '/client_secrets.json')


CLIENT_ID = json.loads(
    open('/var/www/FlaskApps/BartenderAtHome/client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Bartender at Home Application"

# Connect to Database and create database session
engine = create_engine('postgresql://cfio:drinkDB@localhost/drinkcatalogdb')
Base.metadata.bind = engine


DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('/var/www/FlaskApps/BartenderAtHome/client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        login_session['access_token'] = credentials.access_token
        response = make_response(json.dumps(
            'Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    login_session['provider'] = 'google'
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    output += '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# Disconnect from Google login
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = """https://accounts.google.com/o/oauth2/
          revoke?token=%s""" % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access token received %s " % access_token


    app_id = json.loads(open(
        '/var/www/FlaskApps/BartenderAtHome/fb_client_secrets.json', 'r').read())['web']['app_id']
    app_secret = json.loads(
        open('/var/www/FlaskApps/BartenderAtHome/fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = """https://graph.facebook.com/oauth/access_token?
          grant_type=fb_exchange_token&client_id=%s
          &client_secret=%s
          &fb_exchange_token=%s""" % (app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]


# Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"
    '''
Due to the formatting for the result from the server token exchange we have to
split the token first on commas and select the first index which gives us the
key : value for the server access token then we split it on colons to pull out
the actual token value and replace the remaining quotes with nothing so that
it can be used directly in the graph api calls
    '''
    data = json.loads(result)
    token = data.get('access_token')

    url = """https://graph.facebook.com/v2.8/me
            ?access_token=%s&fields=name,id,email""" % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # print "url sent for API access:%s"% url
    # print "API JSON result: %s" % result
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]

    # The token must be stored in the login_session in order to properly logout
    login_session['access_token'] = token

    # Get user picture
    url = """https://graph.facebook.com/v2.8/me/picture?access_token=%s
            &redirect=0&height=200&width=200""" % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    output += '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

    flash("Now logged in as %s" % login_session['username'])
    return output


@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    access_token = login_session.get('access_token')
    url = """https://graph.facebook.com/%s
            /permissions?access_token=%s""" % (facebook_id, access_token)
    h = httplib2.Http()
    h.request(url, 'DELETE')[1]
    return "you have been logged out"


# NEED TO UPDATE
# JSON APIs to view Spirit and Cocktail Information
@app.route('/spirit/<int:spirit_id>/recipes/JSON')
def showRecipesJSON(spirit_id):
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    return jsonify(Recipes=[recipe.serialize for recipe in recipes])


@app.route('/spirit/<int:spirit_id>/recipes/<int:recipe_id>/JSON')
def drinkRecipeJSON(spirit_id, recipe_id):
    drinkRecipe = session.query(Recipe).filter_by(id=recipe_id).one()
    return jsonify(drinkRecipe=drinkRecipe.serialize)


@app.route('/spirit/JSON')
def spiritsJSON():
    spirits = session.query(Spirit).all()
    return jsonify(spirits=[spirit.serialize for spirit in spirits])


# Create user
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    user = session.query(User).filter_by(email=email).one_or_none()
    if not user:
        return None
    return user.id


# Show all spirits
@app.route('/')
@app.route('/spirit/')
@app.route('/spirits/')
def showSpirits():
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    if 'username' not in login_session:
        return render_template('publicSpirits.html', spirits=spirits)
    else:
        return render_template('spirits.html', spirits=spirits)


# Add a new spirit category
@app.route('/spirits/new/', methods=['GET', 'POST'])
def newSpirit():
    if 'username' not in login_session:
        return redirect('/login')
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    if request.method == 'POST':
        newSpirit = Spirit(
            name=request.form['name'],
            description=request.form['description'],
            user_id=login_session['user_id'])
        session.add(newSpirit)
        flash('New Spirit %s Successfully Added' % newSpirit.name)
        session.commit()
        return redirect(url_for('showSpirits', spirits=spirits))
    else:
        return render_template('newSpirit.html', spirits=spirits)


# Edit a spirit
@app.route('/spirit/<int:spirit_id>/edit/', methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/edit/', methods=['GET', 'POST'])
def editSpirit(spirit_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedSpirit = session.query(
        Spirit).filter_by(id=spirit_id).one()
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    creator = getUserInfo(editedSpirit.user_id)
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    if editedSpirit.user_id != login_session['user_id'] or login_session['email'] != 'chris.fiorino@gmail.com':
        return """<script>function myFunction()
            {alert('You are not authorized to edit this spirit. Please cre
            ate your own spirit in order to edit.');}</script><body onload=
            'myFunction()'>"""
    if request.method == 'POST':
        if request.form['description']:
            editedSpirit.description = request.form['description']
        if request.form['name']:
            editedSpirit.name = request.form['name']
            flash('Spirit Successfully Edited %s' % editedSpirit.name)
            return redirect(url_for('showSpirits'))
    else:
        return render_template('editSpirit.html',
                               spirit=editedSpirit,
                               spirits=spirits,
                               recipes=recipes,
                               creator=creator)


# Delete a spirit
@app.route('/spirit/<int:spirit_id>/delete/', methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/delete/', methods=['GET', 'POST'])
def deleteSpirit(spirit_id):
    if 'username' not in login_session:
        return redirect('/login')
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    spiritToDelete = session.query(
        Spirit).filter_by(id=spirit_id).one()
    creator = getUserInfo(spiritToDelete.user_id)
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    if spiritToDelete.user_id != login_session['user_id']:
        return """<script>function myFunction()
        {alert('You are not authorized to delete this spirit. Please
         create your own spirit in order to delete.');}</script>
        <body onload='myFunction()'>"""
    if request.method == 'POST':
        session.delete(spiritToDelete)
        flash('%s Successfully Deleted' % spiritToDelete.name)
        session.commit()
        return redirect(url_for('showSpirits', spirit_id=spirit_id))
    else:
        return render_template('deleteSpirit.html',
                               spirit=spiritToDelete,
                               spirits=spirits,
                               recipes=recipes,
                               creator=creator)


# View recipes using a particular spirit
@app.route('/spirit/<int:spirit_id>/')
@app.route('/spirits/<int:spirit_id>/')
@app.route('/spirit/<int:spirit_id>/cocktails/')
@app.route('/spirits/<int:spirit_id>/cocktails/')
def showRecipes(spirit_id):
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    spirit = session.query(Spirit).filter_by(id=spirit_id).one()
    creator = getUserInfo(spirit.user_id)
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    if 'username' not in login_session or (creator.id !=
                                           login_session['user_id']):
        return render_template('publicRecipes.html',
                               spirits=spirits,
                               recipes=recipes,
                               spirit=spirit,
                               creator=creator)
    else:
        return render_template('recipeList.html',
                               spirits=spirits,
                               recipes=recipes,
                               spirit=spirit,
                               creator=creator)


# Show individual recipe
@app.route('/spirit/<int:spirit_id>/cocktails/<int:recipe_id>/',
           methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktails/<int:recipe_id>/',
           methods=['GET', 'POST'])
def showSelectedRecipe(spirit_id, recipe_id):
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    showSelectedRecipe = session.query(Recipe).filter_by(id=recipe_id).one()
    spirit = session.query(Spirit).filter_by(id=spirit_id).one()
    if 'username' not in login_session:
        return render_template('publicShowSelectedRecipe.html',
                               spirit=spirit,
                               spirit_id=spirit_id,
                               recipe_id=recipe_id,
                               recipe=showSelectedRecipe,
                               recipes=recipes,
                               spirits=spirits)
    if login_session['user_id'] != spirit.user_id:
        return """<script>function myFunction()
                  {alert('You are not authorized to add menu items to this
                   recipe. Please create your own spirit or recipe in order
                   to add items.');}</script><body onload='myFunction()'>"""
    return render_template('showSelectedRecipe.html',
                           spirit=spirit,
                           spirit_id=spirit_id,
                           recipe_id=recipe_id,
                           recipe=showSelectedRecipe,
                           recipes=recipes,
                           spirits=spirits)


# Create a new recipe
@app.route('/spirit/<int:spirit_id>/cocktails/new/', methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktails/new/', methods=['GET', 'POST'])
def newRecipe(spirit_id):
    if 'username' not in login_session:
        return redirect('/login')
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    spirit = session.query(Spirit).filter_by(id=spirit_id).one()
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    if login_session['user_id'] != spirit.user_id:
        return """<script>function myFunction()
                  {alert('You are not authorized to add menu items to this
                   spirit. Please create your own spirit or recipe in order to
                   add items.');}</script><body onload='myFunction()'>"""
    if request.method == 'POST':
        newRecipe = Recipe(
            name=request.form['name'],
            description=request.form['description'],
            ingredients=request.form['ingredients'],
            instructions=request.form['instructions'],
            spirit_id=spirit_id,
            user_id=spirit.user_id)
        session.add(newRecipe)
        session.commit()
        flash('New Menu %s Item Successfully Created' % (newRecipe.name))
        return redirect(url_for('showRecipes',
                                spirits=spirits,
                                recipes=recipes,
                                spirit=spirit,
                                spirit_id=spirit_id))
    else:
        return render_template('newRecipe.html',
                               spirits=spirits,
                               recipes=recipes,
                               spirit=spirit)


# Edit a recipe
@app.route('/spirit/<int:spirit_id>/cocktail/<int:recipe_id>/edit',
           methods=['GET', 'POST'])
@app.route('/spirit/<int:spirit_id>/cocktails/<int:recipe_id>/edit',
           methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktail/<int:recipe_id>/edit',
           methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktails/<int:recipe_id>/edit',
           methods=['GET', 'POST'])
def editRecipe(spirit_id, recipe_id):
    if 'username' not in login_session:
        return redirect('/login')
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    editedRecipe = session.query(Recipe).filter_by(id=recipe_id).one()
    spirit = session.query(Spirit).filter_by(id=spirit_id).one()
    if login_session['user_id'] != spirit.user_id:
        return """<script>function myFunction()
               {alert('You are not authorized to edit menu items to this
                recipe. Please create your own spirit or recipe in order to
                 edit items.');}</script><body onload='myFunction()'>"""
    if request.method == 'POST':
        if request.form['name']:
            editedRecipe.name = request.form['name']
        if request.form['description']:
            editedRecipe.description = request.form['description']
        if request.form['ingredients']:
            editedRecipe.ingredients = request.form['ingredients']
        if request.form['instructions']:
            editedRecipe.instructions = request.form['instructions']
        session.add(editedRecipe)
        session.commit()
        flash('Recipe Successfully Edited')
        return redirect(url_for('showRecipes', spirit_id=spirit_id))
    else:
        return render_template('editRecipe.html',
                               spirit_id=spirit_id,
                               recipe_id=recipe_id,
                               recipe=editedRecipe,
                               spirits=spirits,
                               spirit=spirit,
                               recipes=recipes)


# Edit a recipe
@app.route('/spirit/<int:spirit_id>/cocktail/<int:recipe_id>/delete',
           methods=['GET', 'POST'])
@app.route('/spirit/<int:spirit_id>/cocktails/<int:recipe_id>/delete',
           methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktail/<int:recipe_id>/delete',
           methods=['GET', 'POST'])
@app.route('/spirits/<int:spirit_id>/cocktails/<int:recipe_id>/delete',
           methods=['GET', 'POST'])
def deleteRecipe(spirit_id, recipe_id):
    if 'username' not in login_session:
        return redirect('/login')
    deleteRecipe = session.query(Recipe).filter_by(id=recipe_id).one()
    spirits = session.query(Spirit).order_by(asc(Spirit.name))
    spirit = session.query(Spirit).filter_by(id=spirit_id).one()
    recipes = session.query(Recipe).filter_by(
        spirit_id=spirit_id).all()
    if login_session['user_id'] != spirit.user_id:
        return """<script>function myFunction()
               {alert('You are not authorized to edit menu items to this
                recipe. Please create your own spirit or recipe in order to
                 edit items.');}</script><body onload='myFunction()'>"""
    if request.method == 'POST':
        session.delete(deleteRecipe)
        session.commit()
        flash('%s Recipe Successfully Deleted' % deleteRecipe.name)
        return redirect(url_for('showRecipes', spirit_id=spirit_id))
    else:
        return render_template('deleteRecipe.html',
                               recipes=recipes,
                               spirits=spirits,
                               spirit=spirit,
                               spirit_id=spirit_id,
                               recipe_id=recipe_id,
                               recipe=deleteRecipe)


# Disconnect based on provider
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['username']
            del login_session['email']
            del login_session['picture']
            del login_session['access_token']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showSpirits'))
    if 'username' in login_session:
        del login_session['username']
    if 'email' in login_session:
        del login_session['email']
    if 'picture' in login_session:
        del login_session['picture']
    if 'user_id' in login_session:
        del login_session['user_id']
    if 'access_token' in login_session:
        del login_session['access_token']
    if 'gplus_id' in login_session:
        del login_session['gplus_id']
        """flash("You were not logged in")"""
        return redirect(url_for('showSpirits'))


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
