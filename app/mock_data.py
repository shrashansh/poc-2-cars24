"""
Mock data for the demo. Every name, phone number and registration below is invented.
The complaint patterns are modelled on real public Cars24 reviews (Oct 2025 - Oct 2026).

release_min: minutes relative to app start. Negative = already posted when the demo starts,
positive = "arrives" on the platform during the demo, so the pipeline is seen working live.
"""
import json

POSTS = [
    # --- Seller, RC not transferred, challan after handover, legal threat (Trustpilot) -> verified via case link
    dict(platform="trustpilot", external_post_id="tp-1001", user_id="tp-u-501", handle=None, display_name="Rocky Star",
         title="Sold my car, still in my name", rating=1, release_min=-240,
         body="Sold my car to Cars24 in December. Ownership is still not transferred and I got a ₹10,000 challan "
              "in August for a date after I handed the car over. Emails, calls, WhatsApp, nobody replies. "
              "If this is not fixed I will go to consumer court.",
         edit_min=6, edit_rating=1,
         edit_body="UPDATE: still nothing. Now a second challan has come. Ownership still not transferred after "
                   "10 months. Going to consumer court next week."),
    # --- Same person on X, with the registration number -> merges with the Trustpilot case once verified
    dict(platform="x", external_post_id="x-2001", user_id="x-u-81", handle="@rohan_m", display_name="rohan",
         title=None, rating=None, release_min=4,
         body="@CARS24 RC of DL3CAB4521 is STILL in my name. 10 months since I sold it to you. Third challan now."),
    # --- Repeat poster, booking token refund with deduction (Trustpilot x3)
    dict(platform="trustpilot", external_post_id="tp-1002", user_id="tp-u-777", handle=None, display_name="Arjun S",
         title="Refund not received", rating=1, release_min=-200,
         body="Booking cancelled by Cars24 and I was told the refund is processed. Only ₹10,000 of my ₹15,000 token came back."),
    dict(platform="trustpilot", external_post_id="tp-1003", user_id="tp-u-777", handle=None, display_name="Arjun S",
         title="Now they say non-refundable", rating=1, release_min=-120,
         body="First they said refund processed, now they say ₹5,000 cancellation fee is non-refundable. Nobody told me this when I paid."),
    dict(platform="trustpilot", external_post_id="tp-1004", user_id="tp-u-777", handle=None, display_name="Arjun S",
         title="Posting again", rating=1, release_min=2,
         body="Third review. Filled your form twice. Still no refund of my ₹5,000 and no call back."),
    # --- Buyer warranty (Google)
    dict(platform="google", external_post_id="gg-3001", user_id="gg-u-12", handle=None, display_name="Priya N",
         title=None, rating=1, release_min=-90,
         body="Bought a Kwid from the Tathawade hub on 22 Aug. It broke down twice in six weeks. Warranty ticket was "
              "closed without fixing the gearbox."),
    # --- Seller paid plan, no auction (Play Store), with appointment ID
    dict(platform="playstore", external_post_id="pl-4001", user_id="pl-u-301", handle=None, display_name="Neha G",
         title=None, rating=1, release_min=-60,
         body="Inspector made me pay ₹999 for Selling Pro. Auction never ran. Appointment ID APPT-61873. Refund please."),
    # --- Seller money held back (ConsumerComplaints.in)
    dict(platform="consumercomplaints", external_post_id="cc-5001", user_id="cc-u-vikasy", handle="vikasy", display_name="vikasy",
         title="₹25,000 held back for challans", rating=None, release_min=-150,
         body="Cars24 held ₹25,000 from my sale amount for pending challans. I cleared all challans on 2 Sep. "
              "No refund yet, no reply to mails. Car was a Creta from Noida."),
    # --- Buyer RC delay with booking ID (Trustpilot)
    dict(platform="trustpilot", external_post_id="tp-1005", user_id="tp-u-615", handle=None, display_name="Sana",
         title="6 months, no RC", rating=1, release_min=-30,
         body="Bought a Venue in April, booking BKG-9HTR21. Six months and the RC transfer is still not done. "
              "Every reply says 'actively following up'."),
    # --- Same seller via email ticket and Trustpilot (cross-channel suggestion)
    dict(platform="email", external_post_id="em-6001", user_id="amit.verma@example.com", handle=None, display_name="Amit Verma",
         title="Ticket #2957506 RC not transferred", rating=None, release_min=-400,
         body="My i20 UP15BA2209 was sold to Cars24 in Sep 2025. RC is still not transferred after 13 months and "
              "challans keep coming to me. Ticket #2957506."),
    dict(platform="trustpilot", external_post_id="tp-1006", user_id="tp-u-909", handle=None, display_name="A. Verma",
         title="13 months and RC still not transferred", rating=1, release_min=-100,
         body="Sold my i20 to Cars24 13 months ago. RC still not transferred, challans keep coming to me. Raised a ticket, no reply."),
    # --- Hinglish, seller plan (X)
    dict(platform="x", external_post_id="x-2002", user_id="x-u-44", handle="@gaurav_k", display_name="Gaurav",
         title=None, rating=None, release_min=1,
         body="@CARS24 inspection ke baad ₹1,100 ka plan bech diya, auction hua hi nahi, ab refund bhi nahi de rahe. Bakwas service."),
    # --- Positive review (counted, not cased)
    dict(platform="trustpilot", external_post_id="tp-1007", user_id="tp-u-120", handle=None, display_name="Kiran",
         title="Smooth sale", rating=5, release_min=-50,
         body="Smooth experience selling my Baleno. Payment the same day. Thanks to the Rohini hub team."),
    # --- Valuation drop (Trustpilot)
    dict(platform="trustpilot", external_post_id="tp-1009", user_id="tp-u-332", handle=None, display_name="Huzaif",
         title="High estimate, low offer", rating=1, release_min=-20,
         body="Website estimate was ₹8.9 to 9.8 lakh. After inspection and paying ₹999 the offer was ₹6.1 lakh. No reason given."),
    # --- Buyer: accident misrepresentation (Trustpilot)
    dict(platform="trustpilot", external_post_id="tp-1010", user_id="tp-u-404", handle=None, display_name="M. Rao",
         title="Sold as non-accidental", rating=1, release_min=-10,
         body="Bought a Slavia sold as non-accidental. Skoda service centre found repainted pillars and accident repair."),
    # --- Arrivals during the demo
    dict(platform="trustpilot", external_post_id="tp-1008", user_id="tp-u-818", handle=None, display_name="Real Name Hidden",
         title="Filing police complaint", rating=1, release_min=8,
         body="Sold my car 8 months ago and it is still being driven in my name without transfer. I am filing a police "
              "complaint and sending a legal notice."),
    dict(platform="google", external_post_id="gg-3002", user_id="gg-u-55", handle=None, display_name="Deepak",
         title=None, rating=2, release_min=12,
         body="Price shown online was one thing, then ₹12,000 for RC transfer, ₹6,000 service fee and loan processing fees added at the end."),
    dict(platform="appstore", external_post_id="as-7001", user_id="as-u-9", handle=None, display_name="nidhi",
         title="Stop calling", rating=1, release_min=15,
         body="Sold the car 4 months ago, still get 5 calls a day. Pressing 2 to stop does nothing."),
    dict(platform="trustpilot", external_post_id="tp-1011", user_id="tp-u-660", handle=None, display_name="Sashi",
         title="Challan payment not updated", rating=1, release_min=18,
         body="Paid ₹1,235 for an e-challan through Cars24 a month ago. Still showing unpaid on the government site."),
]

CRM = [
    dict(booking_ref="APPT-50112", crm_ref="CUST-1001", phone="+919811000001", name="Rohan Mehta", kind="sell",
         model="Maruti Swift 2018", reg_no="DL3CAB4521", city="Delhi", hub="Rohini", booking_date="2025-12-05",
         facts={"rc": {"status": "pending", "form29c_ack": "F29C-DL-77812", "handover_date": "2025-12-05"},
                "challans": [{"no": "DL-CH-22104", "amount": 10000, "date": "2026-08-14", "after_handover": True}]}),
    dict(booking_ref="APPT-51990", crm_ref="CUST-1001", phone="+919811000001", name="Rohan Mehta", kind="inspection",
         model="Hyundai i10 2016", reg_no="DL8CBA1199", city="Delhi", hub="Rohini", booking_date="2026-08-02", facts={}),
    dict(booking_ref="BKG-7Q4K2M", crm_ref="CUST-1002", phone="+919811000002", name="Priya Nair", kind="buy",
         model="Renault Kwid 2019", reg_no="MH12KT8890", city="Pune", hub="Tathawade", booking_date="2026-08-22",
         facts={"warranty": {"status": "closed_without_fix", "issue": "gearbox", "claims": 2}}),
    dict(booking_ref="BKG-3FVSQR", crm_ref="CUST-1003", phone="+919811000003", name="Arjun Singh", kind="buy",
         model="Maruti Wagon R 2021", reg_no=None, city="Bengaluru", hub="Kudlu", booking_date="2026-03-24",
         facts={"refund": {"paid": 15000, "refunded": 10000, "deducted": 5000, "reason": "cancellation fee",
                           "status": "partial", "bank_ref": "UTR6212181275"}}),
    dict(booking_ref="APPT-61873", crm_ref="CUST-1004", phone="+919811000004", name="Neha Gupta", kind="sell",
         model="Maruti Baleno 2020", reg_no="HR26DC7851", city="Gurugram", hub="Sector 38", booking_date="2026-10-02",
         facts={"plan": {"name": "Selling Pro", "fee": 999, "auctions_run": 0, "refund_status": "not_refunded"}}),
    dict(booking_ref="APPT-58840", crm_ref="CUST-1005", phone="+919811000005", name="Vikas Yadav", kind="sell",
         model="Hyundai Creta 2019", reg_no="UP16BX3302", city="Noida", hub="Sector 63", booking_date="2026-08-20",
         facts={"holdback": {"amount": 25000, "reason": "pending challans", "challans_cleared_on": "2026-09-02",
                             "status": "held"}}),
    dict(booking_ref="BKG-9HTR21", crm_ref="CUST-1006", phone="+919811000006", name="Sana Sheikh", kind="buy",
         model="Hyundai Venue 2021", reg_no="KA05MR8098", city="Bengaluru", hub="Kudlu", booking_date="2026-04-19",
         facts={"rc": {"status": "pending", "blocker": "seller appearance at RTO required"}}),
    dict(booking_ref="APPT-44120", crm_ref="CUST-1007", phone="+919811000007", name="Amit Verma", kind="sell",
         model="Hyundai i20 2017", reg_no="UP15BA2209", city="Ghaziabad", hub="Raj Nagar", booking_date="2025-09-10",
         facts={"rc": {"status": "pending", "form29c_ack": "F29C-UP-40211", "handover_date": "2025-09-10"},
                "challans": [{"no": "UP-CH-8812", "amount": 2000, "date": "2026-03-02", "after_handover": True}]}),
]


def crm_rows():
    for b in CRM:
        row = dict(b)
        row["facts"] = json.dumps(b["facts"])
        yield row
