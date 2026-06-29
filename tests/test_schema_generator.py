import unittest
import json
import sys
import os

# Ensure the backend directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.schema_generator import align_with_example_structure, generate_all_schemas
import backend.trend_checker

class TestSchemaGeneratorAlignment(unittest.TestCase):
    def setUp(self):
        self.hotel_data = {
            "name": "Pinon Court",
            "description": "Boutique Hotel in Santa Fe New Mexico...",
            "starRating": "3",
            "priceRange": "$$",
            "telephone": "+15059950800",
            "email": "frontdesk@pinoncourt.com",
            "checkinTime": "16:00",
            "checkoutTime": "11:00",
            "websiteUrl": "https://pinoncourt.com/",
            "bookingUrl": "https://bookings.travelclick.com/109342",
            "images": [
                "https://pinoncourt.com/assets/2024/06/pinon-court-og-image.jpg"
            ],
            "address": {
                "streetAddress": "201 Montezuma Ave",
                "addressLocality": "Santa Fe",
                "addressRegion": "New Mexico",
                "postalCode": "87501",
                "addressCountry": "US"
            },
            "social_profiles": [
                "https://www.instagram.com/pinoncourt/",
                "https://www.facebook.com/pinoncourt/"
            ]
        }
        
        self.morrison_example = {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "The Morrison House Boutique Hotel",
            "description": "Experience refined luxury...",
            "image": [
                "https://morrisonhouse.com/assets/2023/02/Exterior.jpeg"
            ],
            "logo": "https://morrisonhouse.com/logo.png",
            "sameAs": [
                "https://www.instagram.com/morrisonhousehotel/",
                "https://www.facebook.com/MorrisonHouse/"
            ],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "116 South Alfred Street",
                "addressLocality": "Alexandria",
                "addressRegion": "VA",
                "postalCode": "22314",
                "addressCountry": "US"
            },
            "geo": {
                "@type": "GeoCoordinates",
                "latitude": "38.8048",
                "longitude": "-77.0469"
            },
            "telephone": "+1-703-838-8000",
            "url": "https://morrisonhouse.com/",
            "priceRange": "$$$",
            "checkinTime": "16:00",
            "checkoutTime": "12:00",
            "starRating": {
                "@type": "Rating",
                "ratingValue": "4",
                "bestRating": "5"
            },
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.4",
                "ratingCount": "430"
            }
        }

    def test_strict_key_conformance(self):
        # Default generated schema has contactPoint, but the Morrison example does not.
        # We want to check that contactPoint is stripped during strict alignment
        # UNLESS it's explicitly allowed (e.g. by guidelines).
        schema = {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "Pinon Court",
            "contactPoint": {
                "@type": "ContactPoint",
                "telephone": "+15059950800"
            }
        }
        
        aligned = align_with_example_structure(
            schema=schema,
            example=self.morrison_example,
            source_data=self.hotel_data,
            allowed_extra_keys=set()
        )
        
        self.assertNotIn("contactPoint", aligned)
        self.assertEqual(aligned.get("name"), "Pinon Court")

    def test_guideline_key_preservation(self):
        # We want to check that keys added by guidelines (like priceCurrency)
        # are preserved even if they are not in the template example.
        schema = {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "Pinon Court",
            "priceCurrency": "EUR"
        }
        
        aligned = align_with_example_structure(
            schema=schema,
            example=self.morrison_example,
            source_data=self.hotel_data,
            allowed_extra_keys={"priceCurrency"}
        )
        
        self.assertIn("priceCurrency", aligned)
        self.assertEqual(aligned.get("priceCurrency"), "EUR")

    def test_fallback_mappings(self):
        # We check that missing fields in schema (like sameAs and logo)
        # are successfully pulled from hotel_data using mappings
        schema = {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "Pinon Court"
        }
        
        aligned = align_with_example_structure(
            schema=schema,
            example=self.morrison_example,
            source_data=self.hotel_data,
            allowed_extra_keys=set()
        )
        
        self.assertIn("logo", aligned)
        self.assertEqual(aligned["logo"], "https://pinoncourt.com/logo.png")
        self.assertIn("sameAs", aligned)
        self.assertEqual(aligned["sameAs"], [
            "https://www.instagram.com/pinoncourt/",
            "https://www.facebook.com/pinoncourt/"
        ])

    def test_nested_objects_conformance(self):
        # Test starRating wrapping from a string "3" in schema to a Rating object in example
        schema = {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "Pinon Court",
            "starRating": "3"
        }
        
        aligned = align_with_example_structure(
            schema=schema,
            example=self.morrison_example,
            source_data=self.hotel_data,
            allowed_extra_keys=set()
        )
        
        self.assertIn("starRating", aligned)
        self.assertIsInstance(aligned["starRating"], dict)
        self.assertEqual(aligned["starRating"].get("@type"), "Rating")
        self.assertEqual(aligned["starRating"].get("ratingValue"), "3")
    def test_schema_modes(self):
        # We test that generate_all_schemas respects schema_mode: both, trends, fed
        hotel_data = {
            "name": "Pinon Court",
            "address": {
                "streetAddress": "201 Montezuma Ave",
                "addressLocality": "Santa Fe"
            }
        }
        pages = [
            {"url": "https://pinoncourt.com/", "page_type": "home", "schema_mode": "both"},
            {"url": "https://pinoncourt.com/rooms", "page_type": "rooms", "schema_mode": "trends"},
            {"url": "https://pinoncourt.com/dining", "page_type": "dining", "schema_mode": "fed"}
        ]
        
        # Mock trend digest to return specific required_properties, deprecated_properties, and example_schemas
        import backend.trend_checker
        original_build = backend.trend_checker.build_trend_digest
        try:
            backend.trend_checker.build_trend_digest = lambda user_id=None: {
                "required_properties": ["faxNumber"],
                "recommended_properties": [],
                "deprecated_properties": ["priceRange"],
                "notes": [],
                "user_guidelines": [],
                "corrections_applied": [],
                "example_schemas": [{
                    "@context": "https://schema.org",
                    "@type": "Hotel",
                    "name": "Example Hotel",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "123 Example St"
                    }
                }],
                "last_updated": "2026-06-19",
                "trends_only": {
                    "required_properties": ["faxNumber"],
                    "recommended_properties": [],
                    "deprecated_properties": ["priceRange"],
                    "example_schemas": []
                },
                "fed_only": {
                    "required_properties": ["taxID"],
                    "recommended_properties": [],
                    "deprecated_properties": ["telephone"],
                    "example_schemas": [{
                        "@context": "https://schema.org",
                        "@type": "Hotel",
                        "name": "Example Hotel",
                        "address": {
                            "@type": "PostalAddress",
                            "streetAddress": "123 Example St"
                        }
                    }],
                    "user_guidelines": []
                }
            }
            
            # Add faxNumber to hotel_data so it can be auto-filled if required
            hotel_data["faxNumber"] = "+15059950801"
            hotel_data["taxID"] = "DE123456789"
            hotel_data["priceRange"] = "$$"
            hotel_data["telephone"] = "+15059950800"
            
            res = generate_all_schemas(hotel_data, pages)
            
            # 1. Page 1: schema_mode = both
            # Should have faxNumber (required) and be aligned with example structure
            page1_schemas = res["https://pinoncourt.com/"]["schemas"]
            hotel_schema1 = next(s for s in page1_schemas if s["@type"] == "Hotel")
            self.assertIn("faxNumber", hotel_schema1)
            self.assertIn("taxID", hotel_schema1)
            self.assertNotIn("priceRange", hotel_schema1) # deprecated stripped
            self.assertNotIn("telephone", hotel_schema1) # deprecated stripped
            
            # 2. Page 2: schema_mode = trends
            # Should have faxNumber (required) but NOT be aligned with example
            page2_schemas = res["https://pinoncourt.com/rooms"]["schemas"]
            hotel_schema2 = next(s for s in page2_schemas if s["@type"] == "Hotel")
            self.assertIn("faxNumber", hotel_schema2)
            self.assertNotIn("taxID", hotel_schema2)
            self.assertNotIn("priceRange", hotel_schema2) # deprecated stripped
            self.assertIn("telephone", hotel_schema2) # not stripped in trends mode
            
            # 3. Page 3: schema_mode = fed
            # Should NOT have faxNumber (required) since trends are skipped
            page3_schemas = res["https://pinoncourt.com/dining"]["schemas"]
            food_schema = next(s for s in page3_schemas if s["@type"] == "FoodEstablishment")
            self.assertNotIn("faxNumber", food_schema)
            self.assertIn("taxID", food_schema)
            self.assertIn("priceRange", food_schema) # not stripped in fed mode
            self.assertNotIn("telephone", food_schema) # deprecated stripped
            
        finally:
            backend.trend_checker.build_trend_digest = original_build


if __name__ == "__main__":
    unittest.main()
