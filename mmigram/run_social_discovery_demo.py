"""
Executable Demo: Social Media Earthquake Media Discovery & QC Routing.

Demonstrates:
  1. Discovery of public earthquake posts using RedditEarthquakeConnector.
  2. Strict discrimination of direct downloadable media (i.redd.it, v.redd.it, galleries) vs metadata-only posts.
  3. Deduplication and earthquake relevance scoring.
  4. Automatic coordinate extraction from captions.
  5. Ingestion of normalized observations into MMI-Gram QC and Human Review Queue.

Usage:
  .venv/bin/python server/mmigram/run_social_discovery_demo.py
"""

import sys
import json
from pathlib import Path

# Add server directory to sys.path
sys.path.insert(0, str(Path(__file__).parents[1]))

from mmigram.ingestion.reddit_connector import RedditEarthquakeConnector, ContentHashDeduplicator
from mmigram.geolocation.validator import validate_coordinates, MYANMAR_BOUNDS
from mmigram.qc.checker import evaluate_quality
from mmigram.core.state import MMIEstimationResult, StructuralDamageAssessment
from mmigram.review.queue import HumanReviewQueue


def main():
    print("=" * 80)
    print("🌍 MMI-GRAM: AUTOMATIC SOCIAL MEDIA EARTHQUAKE MEDIA DISCOVERY")
    print("📡 Ingestion Connector: Reddit Data API (Public Disaster Communities)")
    print("=" * 80)

    fixture_path = Path(__file__).parent / "tests" / "fixtures" / "reddit_earthquake_posts.json"
    deduplicator = ContentHashDeduplicator()
    connector = RedditEarthquakeConnector(
        offline_fixture_path=fixture_path,
        deduplicator=deduplicator,
    )
    review_queue = HumanReviewQueue()

    print("\n🔍 Querying public earthquake posts: query='earthquake damage', min_relevance=0.3...\n")
    discovered_posts = connector.search(query="earthquake damage", limit=10, min_relevance_score=0.3)

    print(f"✅ Discovered {len(discovered_posts)} verified earthquake posts (deduplicated & filtered):\n")

    for i, post in enumerate(discovered_posts, 1):
        rel_score = connector.compute_relevance_score(
            post.raw_payload.get("title", ""), post.raw_payload.get("selftext", "")
        )

        media_status_badge = "📸 [DIRECT MEDIA AVAILABLE]" if post.has_direct_media else "📝 [METADATA / LINK ONLY]"
        attachment_types = [f"{a.media_type} ({a.media_access_status})" for a in post.attachments]

        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[{i}] Post ID: {post.post_id} | Subreddit: r/{post.raw_payload.get('subreddit')} | Author: u/{post.author_id}")
        print(f"    Source URL:    {post.post_url}")
        print(f"    Timestamp:     {post.created_at_utc}")
        print(f"    Media Status:  {media_status_badge}")
        print(f"    Attachments:   {len(post.attachments)} item(s) -> {attachment_types}")
        for att in post.attachments:
            if att.is_direct_media:
                print(f"      🔗 Direct Media URL: {att.media_url}")
        print(f"    Relevance:     {rel_score:.2f} / 1.00")
        print(f"    Title/Caption: {post.text.splitlines()[0]}")

        # Geolocation parsing check
        if post.extracted_coordinates:
            coords = post.extracted_coordinates
            val = validate_coordinates(coords, region_bounds=MYANMAR_BOUNDS)
            print(f"    📍 Extracted Coords: Lat {coords.latitude}, Lon {coords.longitude} (Valid: {val.is_valid}, Authoritative: {coords.is_authoritative})")
        else:
            print(f"    📍 Extracted Coords: None in text caption (Requires visual landmark analysis)")

        # Run through QC and Review queue if direct media is present
        if post.has_direct_media:
            # Simulate initial perception pass on visual evidence
            est = MMIEstimationResult(mmi_value=7.5, confidence=0.80, reasoning="Visual structural cracking in masonry.")
            damage = StructuralDamageAssessment(visual_observations=post.text)
            coords = post.extracted_coordinates or None
            qc = evaluate_quality(coordinates=coords, estimation=est, damage=damage)
            print(f"    🛡️ QC Evaluation: Status: {qc.qc_status} (Flags: {qc.qc_flags})")

            # Route to human review if coordinates are candidate / unverified
            if qc.qc_status != "PASSED" or (coords and not coords.is_authoritative):
                review_item = review_queue.check_and_enqueue(post.post_id, {
                    "source": "reddit",
                    "post_url": post.post_url,
                    "media_urls": [a.media_url for a in post.attachments if a.is_direct_media],
                    "text": post.text,
                    "coordinates": coords.to_dict() if coords else None,
                    "qc": qc.to_dict(),
                }, force=True)
                print(f"    👤 Review Routing: Enqueued for Expert Verification (Queue Item: {post.post_id})")

    print(f"\n" + "=" * 80)
    print(f"📊 SUMMARY OF SOCIAL MEDIA DISCOVERY:")
    print(f"   • Total Posts Evaluated:      8 (including 1 duplicate crosspost, 1 off-topic gaming post)")
    print(f"   • Discovered Valid Posts:     {len(discovered_posts)}")
    print(f"   • Posts with Direct Media:    {sum(1 for p in discovered_posts if p.has_direct_media)} (Real photos/videos ready for MMI analysis)")
    print(f"   • Posts Metadata/Link Only:   {sum(1 for p in discovered_posts if not p.has_direct_media)}")
    print(f"   • Enqueued for Human Review:  {len(review_queue.get_pending())} item(s)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
