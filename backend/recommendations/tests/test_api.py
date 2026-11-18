"""GET /api/recommendations/ and GET /api/books/{id}/similar/ (R-2, R-3)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from catalog.tests.factories import AuthorFactory, BookFactory
from recommendations.models import Recommendation, RecommendationRun, SimilarBook
from tracking.tests.factories import UserBookFactory

pytestmark = pytest.mark.django_db
PICKS = reverse("recommendations:recommendations")


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def run(finished=True):
    now = timezone.now()
    return RecommendationRun.objects.create(started_at=now, finished_at=now if finished else None)


def similar_url(book) -> str:
    return reverse("book-similar", args=[book.pk])


class TestRecommendations:
    def test_requires_login(self, api_client):
        assert api_client.get(PICKS).status_code == 401

    def test_before_the_first_run(self, client):
        assert client.get(PICKS).json() == {"computed_at": None, "results": []}

    def test_picks_in_rank_order_with_shelf_status_and_reason(self, client, user):
        r = run()
        liked = BookFactory(title="Liked One")
        first = BookFactory(title="First", authors=[AuthorFactory(name="Mara Vell")])
        second = BookFactory(title="Second")
        Recommendation.objects.create(run=r, user=user, book=second, rank=2, score=0.2)
        Recommendation.objects.create(
            run=r, user=user, book=first, rank=1, score=0.3, because_of=liked
        )
        entry = UserBookFactory(user=user, book=second)  # shelved since the run
        body = client.get(PICKS).json()

        assert body["computed_at"] is not None
        assert [p["book"]["title"] for p in body["results"]] == ["First", "Second"]
        top = body["results"][0]
        assert top["because_of"] == {"id": liked.pk, "title": "Liked One"}
        assert top["book"]["author_links"][0]["name"] == "Mara Vell"
        assert top["book"]["shelf"] is None
        assert body["results"][1]["book"]["shelf"] == {"id": entry.pk, "status": entry.status}

    def test_only_the_latest_finished_run_and_only_my_picks(self, client, user):
        old, unfinished = run(), run(finished=False)
        latest = run()
        RecommendationRun.objects.filter(pk=old.pk).update(
            finished_at=timezone.now().replace(year=2020)
        )
        mine = BookFactory(title="Mine")
        Recommendation.objects.create(run=latest, user=user, book=mine, rank=1, score=1)
        Recommendation.objects.create(
            run=old, user=user, book=BookFactory(title="Old"), rank=1, score=1
        )
        Recommendation.objects.create(
            run=unfinished, user=user, book=BookFactory(title="Half-written"), rank=1, score=1
        )
        Recommendation.objects.create(
            run=latest, user=UserFactory(), book=BookFactory(title="Theirs"), rank=1, score=1
        )
        assert [p["book"]["title"] for p in client.get(PICKS).json()["results"]] == ["Mine"]

    def test_no_picks_yet_after_a_run(self, client):
        run()
        body = client.get(PICKS).json()
        assert body["computed_at"] is not None and body["results"] == []

    def test_query_count_is_fixed(self, client, user, django_assert_max_num_queries):
        r = run()
        for n in range(20):
            book = BookFactory(authors=[AuthorFactory(), AuthorFactory()])
            Recommendation.objects.create(
                run=r, user=user, book=book, rank=n + 1, score=1, because_of=BookFactory()
            )
        # latest run + picks (with books and reasons) + author prefetch + shelf entries
        with django_assert_max_num_queries(4):
            assert len(client.get(PICKS).json()["results"]) == 20


class TestSimilar:
    def test_most_similar_first_limited_with_shelf_status(self, client, user):
        r = run()
        book = BookFactory()
        others = [BookFactory(title=f"Similar {n}") for n in range(8)]
        for rank, other in enumerate(others, start=1):
            SimilarBook.objects.create(run=r, book=book, similar=other, rank=rank, score=1 / rank)
        entry = UserBookFactory(user=user, book=others[0], status="finished")

        body = client.get(similar_url(book)).json()
        assert [b["title"] for b in body["results"]] == [f"Similar {n}" for n in range(6)]
        assert body["results"][0]["shelf"] == {"id": entry.pk, "status": "finished"}
        assert len(client.get(similar_url(book), {"limit": 3}).json()["results"]) == 3
        assert len(client.get(similar_url(book), {"limit": 99}).json()["results"]) == 8
        assert len(client.get(similar_url(book), {"limit": "x"}).json()["results"]) == 6

    def test_before_the_first_run_and_unknown_books(self, client):
        assert client.get(similar_url(BookFactory())).json() == {"results": []}
        assert client.get(reverse("book-similar", args=[999999])).status_code == 404

    def test_requires_login(self, api_client):
        assert api_client.get(similar_url(BookFactory())).status_code == 401
