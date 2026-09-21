from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from models.model import OrderRefundStatus
import os

# I need to start thinking about some way to dynamically adjust dates to match the status

_zoneinfo = ZoneInfo("America/New_York")

threshold_days_auto_approve = int(os.getenv("DAYS_THRESHOLD_AUTO"))


customer_order_status_map = {
    "wolf.blitzer@cnn.com": [OrderRefundStatus.ORDER_NON_REFUNDABLE_DAYS],
    "pamela.brown@cnn.com": [OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_AMOUNT],
    "anderson.cooper@cnn.com": [OrderRefundStatus.ORDER_AUTO_REFUNDABLE],
    "jake.tapper@cnn.com": [OrderRefundStatus.ORDER_IN_TRANSIT],
    "john.king@cnn.com": [OrderRefundStatus.ORDER_IN_PENDING],
    "harry.enten@cnn.com": [OrderRefundStatus.ORDER_DATA_INVALID],
    "dana.bash@cnn.com": [OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_ITEMS],
    "manu.raju@cnn.com": [OrderRefundStatus.ORDER_DELIVERED_BORDERLINE],
    "sonya_ling1947@yahoo.com": [
        OrderRefundStatus.ORDER_IN_TRANSIT,
        OrderRefundStatus.ORDER_AUTO_REFUNDABLE]
}


def adjust_days_demo_data_testable():
    for email, features in demo_customers.items():
        order_refund_status = customer_order_status_map.get(email)
        for i, order in enumerate(features["latest_orders"]):
            # backfeed missing data
            if order.get("estimated_delivery_date") and order.get("status") == "delivered":
                order["delivery_date"] = order["estimated_delivery_date"]
            match order_refund_status[i]:
                case OrderRefundStatus.ORDER_NON_REFUNDABLE_DAYS:
                    order["delivery_date"] = datetime.now(_zoneinfo) - timedelta(days= threshold_days_auto_approve + 3)
                    _auto_adjust_days(order)
                case OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_AMOUNT | OrderRefundStatus.ORDER_AUTO_REFUNDABLE | OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_ITEMS:
                    order["delivery_date"] = datetime.now(_zoneinfo) - timedelta(days= 25)
                    _auto_adjust_days(order)
                case OrderRefundStatus.ORDER_DELIVERED_BORDERLINE:
                    order["delivery_date"] = datetime.now(_zoneinfo) - timedelta(days= 2)
                    _auto_adjust_days(order)
                # The above all have delivered status   
                case OrderRefundStatus.ORDER_IN_TRANSIT:
                    order["estimated_delivery_date"] = datetime.now(_zoneinfo) + timedelta(days= 2)
                    _auto_adjust_days(order)
                # because of backlog     
                case OrderRefundStatus.ORDER_IN_PENDING:
                    order["order_date"] = datetime.now(_zoneinfo) - timedelta(days= 7)
                case _:
                    pass

def _auto_adjust_days(order: dict):
    if order.get("delivery_date") or order.get("estimated_delivery_date"):
        if order.get("delivery_date"):
            order["estimated_delivery_date"] = order["delivery_date"]
        order["ship_date"] = order["estimated_delivery_date"] - timedelta(days= 5)
        order["order_date"] = order["ship_date"] - timedelta(days= 3)
    
#TODO: Modify to have users with multiple orders.           
demo_customers = {
    "anderson.cooper@cnn.com": {
        "customer_id": 32098,
        "first_name": "Anderson",
        "last_name": "Cooper",
        "title": "Mr.",
        "email": "anderson.cooper@cnn.com",
        "latest_orders":[{
            "order_id": 123456,
            "order_date": datetime(2026, 7, 20, 19, 45, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 156.23,
            "tax_applied_rate": 0.095,
            "status": "delivered",
            "ship_date": datetime(2026, 7, 22, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 7, 25, 12, 45, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999999999999999",
            "items": [{
                "product_id": "PRD-1001",
                "product_name": "Wine Glasses",
                "supplier_name": "Heritage Brands",
                "unit_price": 23.78,
                "number_units": 6,
            }]
        }], 
    },
    "wolf.blitzer@cnn.com": {
            "customer_id": 32099,
            "first_name": "Wolf",
            "last_name": "Blitzer",
            "title": "Mr.",
            "email": "wolf.blitzer@cnn.com",
            "latest_orders":[{
                "order_id": 123457,
                "order_date": datetime(2026, 7, 1, 21, 5, 0, tzinfo= _zoneinfo),
                "total_amount_incl_tax": 84.30,
                "tax_applied_rate": 0.075,
                "status": "delivered",
                "ship_date": datetime(2026, 7, 3, 19, 45, 0, tzinfo= _zoneinfo),
                "estimated_delivery_date": datetime(2026, 7, 7, 12, 45, 0, tzinfo= _zoneinfo),
                "tracking_number": "1Z9999993178999999",
                "items": [{
                    "product_id": "PRD-1015",
                    "product_name": "Bike Light",
                    "supplier_name": "Premier Merchandize",
                    "unit_price": 30.26,
                    "number_units": 2,
                },
                {
                    "product_id": "PRD-1022",
                    "product_name": "Water Bottle",
                    "supplier_name": "United Imports",
                    "unit_price": 17.9,
                    "number_units": 1,
                }]
            }]  
        },
    "pamela.brown@cnn.com": {
        "customer_id": 32100,
        "first_name": "Pamela",
        "last_name": "Brown",
        "title": "Ms.",
        "email": "pamela.brown@cnn.com",
        "latest_orders":[{
            "order_id": 123458,
            "order_date": datetime(2026, 7, 25, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 569.74,
            "tax_applied_rate": 0.075,
            "status": "delivered",
            "ship_date": datetime(2026, 7, 28, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 8, 1, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999993182999999",
            "items": [{
                "product_id": "PRD-1099",
                "product_name": "Sterling Silver White Sapphire Pendant Necklace",
                "supplier_name": "Costal Trading",
                "unit_price": 529.99,
                "number_units": 1,
                },
            ]
        }]  
    },
    "jake.tapper@cnn.com": {
        "customer_id": 32101,
        "first_name": "Jake",
        "last_name": "Tapper",
        "title": "Mr.",
        "email": "jake.tapper@cnn.com",
        "latest_orders":[{
            "order_id": 123459,
            "order_date": datetime(2026, 8, 5, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 118.52,
            "tax_applied_rate": 0.075,
            "status": "transit",
            "ship_date": datetime(2026, 8, 10, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 8, 15, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999993185999999",
            "items": [{
                "product_id": "PRD-1031",
                "product_name": "HDMI Cable",
                "supplier_name": "Coastal Trading",
                "unit_price": 49.22,
                "number_units": 1,
            },
            {
                "product_id": "PRD-1032",
                "product_name": "Bluebooth Adapter",
                "supplier_name": "Coastal Trading",
                "unit_price": 61.03,
                "number_units": 1,
            }
            ]
        }]  
    },
    "john.king@cnn.com": {
        "customer_id": 32102,
        "first_name": "John",
        "last_name": "King",
        "title": "Mr.",
        "email": "john.king@cnn.com",
        "latest_orders":[{
            "order_id": 123460,
            "order_date": datetime(2026, 8, 5, 21, 15, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 63.06,
            "tax_applied_rate": 0.075,
            "status": "pending",
            "notes": "the ordered item is out of stock and wait for the shipment come in",
            "items": [{
                "product_id": "PRD-1156",
                "product_name": "Zip Jacket",
                "supplier_name": "Coastal Trading",
                "unit_price": 29.33,
                "number_units": 2,
                }
            ]
        }]         
    },
    "harry.enten@cnn.com": {
        "customer_id": 32103,
        "first_name": "Harry",
        "last_name": "Enten",
        "title": "Mr.",
        "email": "harry.enten@cnn.com",
        "latest_orders":[{
            "order_id": 123461,
            "total_amount_incl_tax": 63.06,
            "tax_applied_rate": 0.075,
            "status": "pending",
            "notes": "the ordered item is out of stock and wait for the shipment come in",
            "items": [{
                "product_id": "PRD-1156",
                "product_name": "Zip Jacket",
                "supplier_name": "Coastal Trading",
                "unit_price": 29.33,
                "number_units": 2,
                }
            ]
        }]         
    },
    "dana.bash@cnn.com": {
        "customer_id": 32104,
        "first_name": "Dana",
        "last_name": "Bash",
        "title": "Ms.",
        "email": "dana.bash@cnn.com",
        "latest_orders":[{
            "order_id": 123462,
            "order_date": datetime(2026, 7, 25, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 69.82,
            "tax_applied_rate": 0.075,
            "status": "delivered",
            "ship_date": datetime(2026, 7, 28, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 8, 1, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999997933999999",
            "items": [
                {
                "product_id": "PRD-1002",
                "product_name": "Dream Angeles Bras",
                "supplier_name": "Victoria's Secret",
                "unit_price": 64.95,
                "number_units": 1,
                "intimate_item": True,
                },
            ]
        }]  
    },
    "manu.raju@cnn.com": {
        "customer_id": 32105,
        "first_name": "Manu",
        "last_name": "Raju",
        "title": "Mr.",
        "email": "manu.raju@cnn.com",
        "latest_orders":[{
            "order_id": 123463,
            "order_date": datetime(2026, 7, 25, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 105.84,
            "tax_applied_rate": 0.075,
            "status": "delivered",
            "ship_date": datetime(2026, 7, 28, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 8, 1, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999993177999999",
            "items": [
                {
                "product_id": "PRD-1924",
                "product_name": "Zip Jacket",
                "supplier_name": "United Import",
                "unit_price": 31.92,
                "number_units": 1,
                },
                {
                "product_id": "PRD-1906",
                "product_name": "Golf Tees",
                "supplier_name": "Premier Merchandize",
                "unit_price": 11.09,
                "number_units": 6,
                },
            ]
        }]  
    },
    "sonya_ling1947@yahoo.com": {
        "customer_id": 32106,
        "first_name": "Sonya",
        "last_name": "Ling",
        "title": "Ms.",
        "email": "sonya_ling1947@yahoo.com",
        "latest_orders":[{
            "order_id": 123465,
            "order_date": datetime(2026, 9, 15, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 74.02,
            "tax_applied_rate": 0.095,
            "status": "transit",
            "ship_date": datetime(2026, 9, 19, 10, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 9, 23, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z99999996479999990",
            "items": [{
                "product_id": "PRD-1463",
                "product_name": "PowerBank",
                "supplier_name": "National Supply Group",
                "unit_price": 44.74,
                "number_units": 2,
            }]  
            },{
            "order_id": 123464,
            "order_date": datetime(2026, 9, 5, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 74.02,
            "tax_applied_rate": 0.095,
            "status": "delivered",
            "ship_date": datetime(2026, 9, 10, 10, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 9, 12, 14, 30, 0, tzinfo= _zoneinfo),
            "delivery_date": datetime(2026, 9, 15, 18, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999999502999999",
            "items": [{
                "product_id": "PRD-1121",
                "product_name": "Wireless Earbuds",
                "supplier_name": "Summit Wholesale Inc",
                "unit_price": 67.60,
                "number_units": 1,
            }]  
        }]  
    },
}