
from datetime import datetime
from zoneinfo import ZoneInfo

# I need to start thinking about some way to dynamically adjust dates to match the status

_zoneinfo = ZoneInfo("America/New_York")

demo_customers = {
    "anderson.cooper@cnn.com": {
        "customer_id": 32098,
        "first_name": "Anderson",
        "last_name": "Cooper",
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
        "email": "pamela.brown@cnn.com",
        "latest_orders":[{
            "order_id": 123458,
            "order_date": datetime(2026, 7, 25, 21, 10, 0, tzinfo= _zoneinfo),
            "total_amount_incl_tax": 186.02,
            "tax_applied_rate": 0.075,
            "status": "delivered",
            "ship_date": datetime(2026, 7, 28, 19, 45, 0, tzinfo= _zoneinfo),
            "estimated_delivery_date": datetime(2026, 8, 1, 14, 30, 0, tzinfo= _zoneinfo),
            "tracking_number": "1Z9999993182999999",
            "items": [{
                "product_id": "PRD-1016",
                "product_name": "Face Wash",
                "supplier_name": "National Supply Group",
                "unit_price": 14.42,
                "number_units": 12,
            }]
        }]  
    },
    "jake.tapper@cnn.com": {
        "customer_id": 32101,
        "first_name": "Jake",
        "last_name": "Tapper",
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
    }
}