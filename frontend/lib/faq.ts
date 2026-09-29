// GENERATED FILE — do not hand-edit.
// Source of truth: backend/workflow/customer_support_tools.py (FAQs dict).
// Regenerate with: uv run python -m scripts.export_faq (from backend/).

export interface FaqEntry {
  question: string;
  answer: string;
}

export interface FaqSection {
  title: string;
  entries: FaqEntry[];
}

export const FAQ_SECTIONS: FaqSection[] = [
  {
    "title": "Shipping & Delivery",
    "entries": [
      {
        "question": "When will my order ship?",
        "answer": "Orders usually ship in 1 to 2 business days unless the order item is temporarily out of stock.You will get a tracking number link by email when we ship"
      },
      {
        "question": "How long does a delivery take?",
        "answer": "Standard shipping takes 3 to 5 business days. Expedited options are avilable at checkout."
      },
      {
        "question": "How do I track my order?",
        "answer": "Using the tracking number included in the shipping confirmation email."
      },
      {
        "question": "Do you ship internationally?",
        "answer": "Yes, to select countries. Shipping costs show at checkout."
      },
      {
        "question": "What if my package is lost or late?",
        "answer": "Check your tracking link first. Contact us if you still have trouble to get it on time"
      }
    ]
  },
  {
    "title": "Exchange, Return and Refund",
    "entries": [
      {
        "question": "How do I choose between exchange and return?",
        "answer": "Exchange when your item has wrong size or fit or you want a different color or style or the product arrived broken or doesn't work and you want a fresh replacement. Return when the product didn't meet expectations or you change your mind entirely or the product you like to exchange with is out of stock"
      },
      {
        "question": "How do I start an exchange? ",
        "answer": "Go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange. We'll include the return shipping label in the confirmation email and ship the exchange once the original item is scanned by the carrier."
      },
      {
        "question": "What items cannot be returned?",
        "answer": "We cannot accept returns on final sale items, customized items, perishable items, gift cards, or items that have been altered or damaged by the customer. Certain high-risk items, such as electronics, luxury goods and intimate items, are marked as non-returnable unless they are defective or damaged upon receipt."
      },
      {
        "question": "What is your return policy in summary?",
        "answer": "We accept returns within 35 days of delivery for unused items.  The return item must have its tags attached and be returned in its original packaging with your receipt or proof of purchase"
      },
      {
        "question": "Can I still get my refund if my order exceeds the return window of the policy",
        "answer": "No, we have already extended 5 more days."
      },
      {
        "question": "How do I start a return?",
        "answer": "You can talk to me to start a return/ refund request."
      },
      {
        "question": "When will I get my refund?",
        "answer": "Refunds usually take 3 to 5 business days after we get the item back."
      },
      {
        "question": "Are returns free?",
        "answer": "We are not charging any re-stocking fees. However, you will return at your own expense unless for defective, damaged or wrong items. We do cover the return shipping label if you exchange instead."
      }
    ]
  },
  {
    "title": "Orders and Payment",
    "entries": [
      {
        "question": "What payment methods do you accept?",
        "answer": "We take credit/ debit cards, PayPal, Apple Pay, and Google Wallet."
      },
      {
        "question": "Would you price match if your competitor offer a better price?",
        "answer": "We will price match on selective items."
      },
      {
        "question": "Can I cancel my order?",
        "answer": "You can cancel your order as long as the order is in pending status.  You cannot cancel an order once it has been shipped and in transit status."
      },
      {
        "question": "Is my payment secure?",
        "answer": "Yes. All data is encrypted via SSL."
      }
    ]
  }
];
