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
    "title": "Returns and Refunds",
    "entries": [
      {
        "question": "What is your return policy?",
        "answer": "We accept returns within 35 days of delivery for unused items"
      },
      {
        "question": "Can I still get my refund if my order exceeds the return window of the policy",
        "answer": "Sorry, we have already extended 5 more days."
      },
      {
        "question": "How do I start a return?",
        "answer": "You can talk to me to start a return/ refund request."
      },
      {
        "question": "When will I get my refund?",
        "answer": "Refunds usually take 7 to 10 business days after we get the item back."
      },
      {
        "question": "Are returns free?",
        "answer": "Yes, we will include the return shipping label in the request confirmation email"
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
