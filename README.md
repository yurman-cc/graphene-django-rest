# graphene-django-rest
Extend your Django graphene data point (GraphQL) with arbitrary queries (for legacy APIs etc.)

Author:    http://yurman.cc
Published: https://github.com/yurman-cc/graphene-django-rest
Copyright: MIT (the same as https://github.com/graphql-python/graphene-django)
Date:      2018-11-22

This is just a snippet of Django code that extends graphene (more specifically: GraphQL implementation
in Python for Django) to support arbitrary legacy http API you need to support thus avoiding maintaining
separate data points for the two. If the legacy API fails then the request is routed to the normal graphene
processing. I implemented this to keep my interface compliant with a third-party API which I'm planning
to extend in the future with GraphQL. Implementing this particular third-party API allows me to run many
available clients against my own server serving the data so it saves me a great deal of effort!

The code specific to my server implementation is left for clarity and marked with +++ ---. You will want
 to drop that and replace as needed.

This code was tested on the live server installation in the following environment:
Django 1.11, 2.1.4
graphene 2.1.3
graphene-django 2.2.0
