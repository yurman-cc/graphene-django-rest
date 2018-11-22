# Author:    http://yurman.cc
# Published: https://github.com/yurman-cc/graphene-rest
# Copyright: MIT (the same as https://github.com/graphql-python/graphene-django)
# Date:      2018-11-22
#
# This is just a snippet of Django code that extends graphene (more specifically: GraphQL implementation
# in Python for Django) to support arbitrary legacy http API you need to support thus avoiding maintaining
# separate data points for the two. If the legacy API fails then the request is routed to the normal graphene
# processing. I implemented this to keep my interface compliant with a third-party API which I'm planning
# to extend in the future with GraphQL. Implementing this particular third-party API allows me to run many
# available clients against my own server serving the data so it saves me a great deal of effort!
#
# The code specific to my server implementation is left for clarity and marked with +++ ---. You will want
# to drop that and replace as needed.
#
# This code was tested on the live server installation in the following environment:
# Django 1.11
# graphene 2.1.3
# graphene-django 2.2.0


from django.conf.urls import url

#+++
from qhost import views
#---

# GraphQL interception
import sys
import traceback
from json import loads, dumps
import re

from django.contrib import admin
from django.http.response import HttpResponse, HttpResponseNotAllowed
from django.utils.datastructures import MultiValueDict

from graphene_django.views import GraphQLView
from graphql.execution import ExecutionResult

from quotesrv import server


#
# Unfortunately, to return the quotes in the XYZ-lib format we have to bypass the entire GraphQL machinery
# to be able to return a custom json (arbitrary key names (time), a dictionary - either one NOT supported by GraphQL)
# This way, we support many clients already running on AV with just a small tweak!!
#

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie


class HttpError(Exception):
    def __init__(self, response, message=None, *args, **kwargs):
        self.response = response
        self.message = message = message or response.content.decode()
        super(HttpError, self).__init__(message, *args, **kwargs)


class QhostGraphQLView(GraphQLView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dataSrv = server.Server('pyz/tickdata')

    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, request, *args, **kwargs):

        # Unfortunately, GraphQL only supports a fixed set of url params ('query' etc.) so intercepting
        # execute_graphql_request() is not enough - have to intercept dispatch()

        # Uncomment this line to run in pure GraphQL mode
        #return super().dispatch(request, *args, **kwargs)

        try:
            if request.method.lower() not in ("get", "post"):
                raise HttpError(
                    HttpResponseNotAllowed(
                        ["GET", "POST"], "GraphQL only supports GET and POST requests."
                    )
                )

            # Check and validate if this is a special quotes request that bypasses all
            res, jsTrail = self.processRawRequest(request)
            if res.status_code == 200:
                return res
            else:
                if jsTrail != '' and jsTrail[0] == '#':
                    jsTrail = jsTrail[2:]
                    # This is a quick re hack to drop the non-GraphQL query portion
                    # TODO: do it properly by tracking the offsets of the original sequence when parsing
                    body_txt = request.body.decode('utf-8')
                    body_txt = re.sub(r'\:".*?#', ':"', body_txt)
                    request._body = body_txt.encode('utf-8')
                    if 'query' in request.GET:
                        request.GET._mutable = True
                        request.GET['query'] = jsTrail
                        request.GET._mutable = False
                return super().dispatch(request, *args, **kwargs)
        except HttpError as e:
            response = e.response
            response["Content-Type"] = "application/json"
            response.content = self.json_encode(
                request, {"errors": [self.format_error(e)]}
            )
            return response

    def processRawRequest(self, request):

        # This one won't get returned to the client but will trigger
        # the normal GraphQL code path in the case of error
        res = HttpResponse(status=402)

        req = request.body.decode('utf-8')

        jsTrail = ''
        js = ''

        try:
            txt = ''

            if req != '':
                # Body: Load and un-escape (nested json)
                txt = loads(req)['query'].replace('\\\\', '\\')
            else:
                # Assume URL
                try:
                    req = request.GET['query']
                except:
                    # Non-GrpahQL format.. REST?
                    pass

                if req != '':
                    txt = req
                else:
                    # Unfold REST params back into one json string
                    try:
                        js = dumps(request.GET)

                        # Empty the URL parameters as these ones are invalid for GraphQL consumption
                        request.GET = MultiValueDict()
                    except:
                        return res, ''

            if js == '':
                # Allow for arbitrary trailing text in the body (to pass on to GraphQL etc. potentially)
                js = txt[:txt.find('}')+1]
                jsTrail = txt[txt.find('}')+1:].strip()
                # Allow for single quotes (invalid in json)
                js = js.replace('\'', "\"")

            response = self.execute_graphql_request(None, None, js, None, None, False)
            if response.invalid:
                #res = HttpResponse(status=200, content=response, content_type='application/json')

                # Assume the original GraphQL request. This will get us the generic error message
                # The downside is that specific errors will be masked by the general GraphQL one
                pass
            else:
                # Success!
                # NOTE: If none of the objects are matched, an empty string is still returned with 200
                res = HttpResponse(status=200, content=response.data, content_type='application/json')

        except:
            traceback.print_exception(*sys.exc_info())
            pass

        # Pass on the trailing request part to the original GraphQL request
        return res, jsTrail

    def execute_graphql_request(
                            self,
                            request,
                            data,
                            query,
                            variables,
                            operation_name,
                            show_graphiql=False
                            ):

        # Back to normal GraphQL processing?
        if  (request != None) or (query == None):
            return super().execute_graphql_request(
                                            request,
                                            data,
                                            query,
                                            variables,
                                            operation_name,
                                            show_graphiql
                                            )

        # Handle the REST-style request by our data processing lib
        try:
            params = loads(query.replace('\'', "\""))

            try:
                # +++

                #
                # Integrate the real data!
                #

                # Where to take it from and in which format:
                srcName     = 'av'  # this one can be anything - just a sub-folder name in the server config
                ifaceName   = 'av'  # support XYZ client lib

                if not self.dataSrv.validateApiKey(
                                            params['apikey'],
                                            srcName=srcName,
                                            ifaceName=ifaceName
                                            ):
                    raise Exception('Bad apikey')

                # This one is special (backward-compatible + arbitrary time period (seconds) is supported)
                period = params['function']
                if ifaceName == 'av':
                    if period == 'TIME_SERIES_DAILY':
                        period = 24*3600
                period = int(period)

                res = self.dataSrv.integrateDataOnDemand(
                                            params['symbol'],
                                            period,
                                            params['start'],
                                            params['end'],
                                            srcName=srcName,
                                            ifaceName=ifaceName
                                            )

                # ---
                res = res.encode('utf-8')

            except Exception as e:
                traceback.print_exception(*sys.exc_info())
                return ExecutionResult(errors=[e], invalid=True)

        # Be silent in pure pass-through (invalid json etc.) letting graphene handle it
        except Exception as e:
            return ExecutionResult(errors=[e], invalid=True)

        return ExecutionResult(data=res, invalid=False)


urlpatterns = [
    # GraphQL
    url(r'^admin/', admin.site.urls),
    url(r'^graphql', QhostGraphQLView.as_view(graphiql=True)),

    url(r'^$', views.hello, name='hello'),
]
