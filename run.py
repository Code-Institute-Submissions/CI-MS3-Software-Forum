import os
import datetime
import pymongo
import math
import uuid
from flask import Flask, render_template, redirect, request, url_for, jsonify, make_response
from flask_pymongo import PyMongo
from bson.objectid import ObjectId


from os import path

app = Flask(__name__)

if path.exists("env.py"):
    import env

app.config["MONGO_URI"] = os.environ.get("MONGO_URI")
app.config["MONGO_DBNAME"] = 'software_forum'


mongo = PyMongo(app)


class SearchFilters:
    """
    Class used to save filter settings in the back end
    """
    searchKeyword = ".*"
    searchScope = ["titles", "details", "comments.comment_text"]
    dateOrder = -1
    platform = ['Windows', 'MacOS', 'Linux', 'Android', 'iOS', 'Other']
    cost = ".*"
    answers = "All"

    def resetFilters(self):
        self.searchKeyword = ".*"
        self.searchScope = ["titles", "details", "comments.comment_text"]
        self.dateOrder = -1
        self.platform = ['Windows', 'MacOS', 'Linux', 'Android', 'iOS', 'Other']
        self.cost = ".*"
        self.answers = "All"


class PaginationSettings:
    """
    Class used for pagination. Data is used in the front end for
    the pagination functionality (below the topics table)
    """
    p_limit = 10
    p_offset = num_results = num_pages = active_page = 0

    def resetSettings(self):
        self.p_limit = 10
        self.p_offset = 0
        self.num_results = mongo.db.topics.find().count()
        self.num_pages = math.ceil(self.num_results / self.p_limit) + 1
        self.active_page = int(self.p_offset / self.p_limit + 1)


newtopic_form = {
    "pre_title": "",
    "pre_name": "",
    "pre_details": "",
    "pre_platform": [],
    "pre_cost": "Any"
}


"""
Used to check if the user has rated a comment or not (to avoid
multiple ratings for 1 comment)
"""
rated_comments_neg = ["0"]
rated_comments_pos = ["0"]


searchFilters = SearchFilters()
pagination = PaginationSettings()


@app.route('/')
@app.route('/home')
def home():
    """
    entry point
    """
    searchFilters.resetFilters()
    pagination.resetSettings()
    return render_template("index.html", args=newtopic_form)


@app.route('/get_topics')
def get_topics():
    """
    render the main page
    """
    return render_template(
        "topicstable.html", topics=apply_filters(), paginationOpt=pagination)


@app.route('/pagination_plus')
def pagination_plus():
    """
    One page further - User selects arrow-right in pagination
    """
    pagination.p_offset += pagination.p_limit
    # make sure the number is not too high
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/pagination_minus')
def pagination_minus():
    """
    One page back - User selects arrow-left in pagination
    """
    pagination.p_offset -= pagination.p_limit
    # make sure the number is not too low
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/pagination_random/<value>')
def pagination_random(value):
    """
    Go to page x - User selects a random page-number in pagination
    """
    pagination.p_offset = pagination.p_limit * (int(value) - 1)
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/rate_pos/<topic_id>/<comment_id>')
def rate_pos(topic_id, comment_id):
    """
    User rates a comment positive (selects thumbs-up)
    Receiving the topic _id (unique id of the topic inside the collection)
    and the comment _id (unique id of the comment inside the topic)
    """
    thumbs_number = comment_rating(topic_id, comment_id, 1, 0)
    return jsonify({'totalThumbs': thumbs_number})


@app.route('/rate_neg/<topic_id>/<comment_id>')
def rate_neg(topic_id, comment_id):
    """
    User rates a comment negative (selects thumbs-down)
    Receiving the topic _id (unique id of the topic inside the collection)
    and the comment _id (unique id of the comment inside the topic)
    """
    thumbs_number = comment_rating(topic_id, comment_id, 0, 1)
    return jsonify({'totalThumbs': thumbs_number})


@app.route('/search_topics/<search_keyword>/<search_scope>')
def search_topics(search_keyword, search_scope):
    """
    Called when user enters a search keyword or changes the search scope.
    Definition is called after every keystroke + a short delay defined in js
    """
    searchFilters.searchKeyword = search_keyword
    searchFilters.searchScope = search_scope.split(",")
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/sort_topics_date/<date_order>')
def sort_topics_date(date_order):
    """
    User changes the order of the topics according to the date stamp in the document.
    Either from ascending (1) --> descending (-1), or from descending --> ascending
    """
    searchFilters.dateOrder = int(date_order)
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/filter_topics_platform/<platform_filter>')
def filter_topics_platform(platform_filter):
    """
    User selects/deselects certain os/platforms in the search
    """
    filter_list = platform_filter.split(",")
    searchFilters.platform = filter_list
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/filter_topics_cost/<cost_filter>')
def filter_topics_cost(cost_filter):
    """
    User changes the cost radio-button in the search: Free / Paid / All
    """
    if cost_filter == "All":
        cost_filter = ".*"
    searchFilters.cost = cost_filter
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/filter_topics_answer/<answer_filter>')
def filter_topics_answer(answer_filter):
    """
    User changes the answer search (filter if the topics are answered or not)
    """
    searchFilters.answers = answer_filter
    return render_template(
        'topicstable.html', topics=apply_filters(), paginationOpt=pagination)


@app.route('/reset_filters')
def reset_filters():
    """
    User clicks on the link 'reset search options' below the table
    """
    searchFilters.resetFilters()
    pagination.resetSettings()
    return redirect(url_for('home'))


@app.route('/insert_topic', methods=['POST'])
def insert_topic():
    """
    Called when the user saves a new topic
    """
    received_dict = request.form.to_dict()
    received_dict.update({'os': request.form.getlist('os')})
    received_dict['publish_date'] = datetime.datetime.utcnow()

    # check for empty fields or selection
    check_result = check_inputform(received_dict)

    # save comment if validation passed
    if check_result[0]:
        topics = mongo.db.topics
        topics.insert_one(received_dict)

        # making sure the input form is empty when reloading the page
        global newtopic_form
        newtopic_form = {
            "pre_title": "",
            "pre_name": "",
            "pre_details": "",
            "pre_platform": [],
            "pre_cost": "Any"
        }
        return redirect(url_for('home'))

    # go to errortopic.html if validation didn't pass
    else:
        # pass the faulty fields to the error page
        args = check_result[1]

        # Make sure the input is still there when returning from error page
        newtopic_form["pre_title"] = received_dict['title']
        newtopic_form["pre_name"] = received_dict['author']
        newtopic_form["pre_details"] = received_dict['details']
        newtopic_form["pre_platform"] = received_dict['os']
        newtopic_form["pre_cost"] = received_dict['cost']

        return render_template("errortopic.html", args=args)


@app.route('/edit_topic/<topic_id>')
def edit_topic(topic_id):
    """
    opens the page 'edittopic.html" with a pre-filled form
    to change the fields of a topic
    """
    active_topic = mongo.db.topics.find_one({"_id": ObjectId(topic_id)})
    return render_template('edittopic.html', topic=active_topic)


@app.route('/update_topic/<topic_id>', methods=["POST"])
def update_topic(topic_id):
    """
    Called when saving the form with the topic which was changed
    """
    received_dict = request.form.to_dict()
    received_dict.update({'os': request.form.getlist('os')})

    # check for empty fields or selection
    check_result = check_inputform(received_dict)

    # save comment if validation passed
    if check_result[0]:
        topics = mongo.db.topics
        active_topic = topics.find_one(
            {"_id": ObjectId(topic_id)}, {'publish_date': 1, 'comments': 1})
        timestamp = active_topic['publish_date']
        all_fields = {
            'title': request.form.get('title'),
            'details': request.form.get('details'),
            'author': request.form.get('author'),
            'os': request.form.getlist('os'),
            'cost': request.form.get('cost'),
            'publish_date': timestamp
        }

        # check if comments exist. If yes, make them expired
        if 'comments' in active_topic:
            comments = active_topic['comments']
            for item in comments:
                comments[comments.index(item)]['expired'] = True

            all_fields['comments'] = comments

        topics.update({'_id': ObjectId(topic_id)}, all_fields)
        return redirect(url_for('home'))

    # go to errortopic.html if validation didn't pass
    else:
        # pass the faulty fields to the error page
        args = check_result[1]

        return render_template("errortopic.html", args=args)


@app.route('/delete_topic/<topic_id>')
def delete_topic(topic_id):
    """
    called when the user clicks on 'delete topic'
    """
    mongo.db.topics.remove({'_id': ObjectId(topic_id)})
    return redirect(url_for('home'))


@app.route('/insert_comment/<topic_id>', methods=['POST'])
def insert_comment(topic_id):
    """
    Called when user saves a comment
    """
    topics = mongo.db.topics

    comment_text = request.form.get('comment_text')
    comment_author = request.form.get('comment_author')

    # defensive programming: check user input
    commentExist = False
    commentOver = True
    authorExist = False
    authorOver = True

    if comment_text:
        commentExist = True
        if len(comment_text) > 400:
            commentOver = False

    if comment_author:
        authorExist = True
        if len(comment_author) > 40:
            authorOver = False

    # save comment if validation passed
    if commentExist and commentOver and authorExist and authorOver:
        one_object = {
            'comment_text': comment_text,
            'comment_author': comment_author,
            'comment_pos': 0,
            'comment_neg': 0,
            'popularity': 0,
            'expired': False,
            'comment_id': str(uuid.uuid4())
        }

        topics.update(
            {'_id': ObjectId(topic_id)}, {'$push': {'comments': one_object}})
        return redirect(url_for('home'))

    # go to errorcomment.html if validation didn't pass
    else:
        args = {
            "commentExist": commentExist,
            "commentOver": commentOver,
            "authorExist": authorExist,
            "authorOver": authorOver,
        }

        return render_template("errorcomment.html", args=args)


def comment_rating(topic_id, comment_id, positive, negative):
    """
    Get comment rating, add (+1 / -1) to the rating, sort comments according
    to popularity and update the topic with the sorted + updated comments
    """
    topics = mongo.db.topics
    topic = topics.find_one({'_id': ObjectId(topic_id)})
    all_comments = topic['comments']
    for i, item in enumerate(all_comments):
        if item['comment_id'] == comment_id:
            one_comment = item
            index = i
            break

    if positive == 1 and check_rating_pos(one_comment['comment_id']):
        positive = -1

    if negative == 1 and check_rating_neg(one_comment['comment_id']):
        negative = -1

    thumbs_up = one_comment['comment_pos']
    thumbs_down = one_comment['comment_neg']
    thumbs_up += positive
    thumbs_down += negative
    one_comment['comment_pos'] = thumbs_up
    one_comment['comment_neg'] = thumbs_down
    one_comment['popularity'] = thumbs_up - thumbs_down
    all_comments[index] = one_comment
    all_comments.sort(reverse=True, key=get_key)
    topics.update_one({'_id': ObjectId(topic_id)}, {
        '$set': {'comments': all_comments}
    })
    if negative == 0:
        return thumbs_up
    else:
        return thumbs_down


def get_key(e):
    """
    used in the comment_rating definition in order to sort the comments
    according to its popularity
    """
    return e['popularity']


def check_rating_pos(comment):
    """
    making sure the user doesn't rate the same comment more than once positive
    """
    value = False
    for item in rated_comments_pos:
        if comment == item:
            value = True
            rated_comments_pos.remove(comment)
            break

    if not value:
        rated_comments_pos.append(comment)

    return value


def check_rating_neg(comment):
    """
    making sure the user doesn't rate the same comment more than once positive
    """
    value = False
    for item in rated_comments_neg:
        if comment == item:
            value = True
            rated_comments_neg.remove(comment)
            break

    if not value:
        rated_comments_neg.append(comment)

    return value


def check_inputform(received_dict):
    """
    Check user input on forms for a new topic and to change a topic
    (defensive programming)
    """
    titleExist = authorExist = detailsExist = False
    titleOver = authorOver = detailsOver = True
    platformSelected = False

    if received_dict['title']:
        titleExist = True
        if len(received_dict['title']) > 40:
            titleOver = False

    if received_dict['author']:
        authorExist = True
        if len(received_dict['author']) > 40:
            authorOver = False

    if received_dict['details']:
        detailsExist = True
        if len(received_dict['details']) > 400:
            detailsOver = False

    if received_dict['os']:
        platformSelected = True

    if titleExist and authorExist and detailsExist and titleOver and authorOver and detailsOver and platformSelected:
        return True, None

    else:
        args = {
            "titleExist": titleExist,
            "authorExist": authorExist,
            "detailsExist": detailsExist,
            "titleOver": titleOver,
            "authorOver": authorOver,
            "detialsOver": detailsOver,
            "platformSelected": platformSelected
        }
        return False, args


def apply_filters():
    """
    get all Topics with search, filters and pagination applied
    """
    searchInclude = []
    for item in searchFilters.searchScope:
        searchInclude.append(
            {item: {'$regex': searchFilters.searchKeyword, '$options': 'i'}})

    allFilters = [
        {"$or": searchInclude},
        {"os": {"$in": searchFilters.platform}},
        {"cost": {"$regex": searchFilters.cost}}]

    if searchFilters.answers == "Answered":
        allFilters.append({"comments": {"$exists": True, "$ne": None}})

    elif searchFilters.answers == "Unanswered":
        allFilters.append({"comments": {"$exists": False}})

    try:
        # 1. Apply filters the first time: Get all topics
        topics = mongo.db.topics
        search_total = topics.find(
            {"$and": allFilters}).sort('publish_date', searchFilters.dateOrder)
        pagination.num_results = search_total.count()
        pagination.num_pages = math.ceil(pagination.num_results / pagination.p_limit) + 1
        pagination.active_page = int(pagination.p_offset / pagination.p_limit + 1)
        last_date = search_total[pagination.p_offset]['publish_date']

        # Making sure pagination works correctily with the ascending/descending order of the date
        if searchFilters.dateOrder == -1:
            allFilters.append({'publish_date': {'$lte': last_date}})

        else:
            allFilters.append({'publish_date': {'$gte': last_date}})

        # 2. Apply filters the second time: because of pagination
        search_result = topics.find(
            {"$and": allFilters}).sort('publish_date', searchFilters.dateOrder).limit(pagination.p_limit)

    except IndexError:
        search_result = None

    return search_result


if __name__ == '__main__':
    app.run(host=os.environ.get('IP'),
        port=int(os.environ.get('PORT')),
        debug=False)
