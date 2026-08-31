var error_msg = {
  academic_year: "Academic Year is required before proceeding ahead",
  center: "School is required before proceeding ahead",
  first_name: "First name is required before proceeding ahead",
  fathers_phone: "Father's phone number is required before proceeding ahead",
  class: "Class is required before proceeding ahead",
  fathers_email: "father's email id is required before proceeding ahead",
  gender: "Gender is required before proceeding ahead",
};

var subStatuses = {
  fresh: [
    "Not Known",
    "Online Enquiry",
    "Telephonic Enquiry",
    "Walkin Enquiry",
  ],
  warm: ["Center Visit Planned", "School Visit Done"],
  "followup/callback": [
    "Call back later",
    "Call not answering",
    "Curious",
    "Interaction Done",
    "Not Reachable",
    "School Visit Done",
    "Switched Off",
    "Trial Class",
  ],
  hot: [
    "Followup for Enrollment",
    "Interested-Will Enroll",
    "School Visit Done",
  ],
  cold: [
    "Added in Waiting List",
    "Enrolled in another school",
    "Fees High",
    "Junk/Invalid",
    "Location not Convenient",
    "Rejected",
    "Schedule not Convenient",
    "School Visit Done",
  ],
  enrolled: ["Admission Taken"],
  "existing parents": ["Already Enrolled"],
  "old leads": ["Old lead"],
  closed: ["zxc"],
};

const DEMO_WHATSAPP_USER = 'system.manager.demo@unityedu.tech';
const DEMO_WHATSAPP_LEAD = 'SH-LD-341237';
const DEMO_WHATSAPP_ASSET = '/unity-demo/om-kale-whatsapp-demo';

function shouldOpenDemoWhatsapp(frm) {
  return frappe.session?.user === DEMO_WHATSAPP_USER && frm?.doc?.name === DEMO_WHATSAPP_LEAD;
}

function openDemoWhatsapp() {
  window.location.href = `${window.location.origin}${DEMO_WHATSAPP_ASSET}`;
}

function queryWalkInAttendedBy(frm) {
  [1, 2, 3].forEach((el) => {
    frm.set_query(`custom_walk_in_${el}_attended_by`, function () {
      return {
        query: "edu_quality.public.py.lead.walk_in_attended_by_query",
        filters: {
          school: frm.doc.center,
        },
      };
    });
  });
}
frappe.ui.form.on("Lead", {
  refresh: function (frm) {
    if (frm.doc.status === "Hot" && frm.doc.custom_re_enquired_count) {
      frm.page.set_indicator(
        "Hot " + frm.doc.custom_re_enquired_count,
        "orange"
      );
    }
    frm.set_intro(
      `
        <p class="text-dark my-0">
            These fields are required before proceeding ahead:<ul><li>Academic Year</li><li> School</li><li>First Name</li><li>Date of Birth</li><li>Fathers Phone</li><li>Class</li><li>Fathers Email</li><li>Gender</li>

      `,
      "orange"
    );
    setTimeout(() => {
      frm.clear_custom_buttons();

      // <div style="display:flex;align-items:center;gap:4px;"><img alt="open whatsapp ui" src="/assets/edu_quality/img/whatsapp-icon.png" style="height:100%;object-fit:contain;background-repeat:no-repeat;max-height:19.5px" /><div>Open in Whatsapp UI</div></div>`
      frm.add_custom_button(
        __(`Open in Whatsapp UI`),
        async function () {
          const contactsWithPhone = await fetch(
            `/api/resource/Contact?fields=[%22name%22]&filters=[[%22mobile_no%22,%22like%22,%22%25${frm.doc.fathers_phone}%25%22]]&order_by=creation%20desc&limit=1`,
            {
              headers: (() => {
                const headers = new Headers();
                headers.append("X-Frappe-CSRF-Token", frappe.csrf_token);
                return headers;
              })(),
            }
          );
          const contacts = await contactsWithPhone.json();
          if (contacts?.data && contacts?.data?.length) {
            window.location.href =
              window.location.origin +
              "/app/whatsapp_manager?user=" +
              contacts?.data?.[0]?.name;
          }
          // })
        },
        "",
        "Open in whatsapp ui"
      );
      if (
        frm.doc.status != "Applied" &&
        frm.doc.status != "Enrolled" &&
        frm.doc.status != "Enrollment Pending"
      ) {
        frm.set_df_property("status", "read_only", 0);
        frm.add_custom_button(__("Create Admission"), function () {
          var errorKey = Object.keys(error_msg).find(
            (error) =>
              frm.doc[error] === null ||
              frm.doc[error] === undefined ||
              frm.doc[error] === ""
          );
          if (String(frm.doc.fathers_phone).length != 10) {
            frappe.msgprint({
              message: __(
                "Fathers Phone Number format is invalid, Please check the spacing is according to standard phone number spacing or none at all, and country code shouldn't be there for Indian numbers only for foreign numbers. and please make sure the number is 10 digits only before proceeding ahead"
              ),
              indicator: "red",
              title: __("Incorrect Field"),
            });
            return;
          }
          if (errorKey) {
            frappe.msgprint({
              title: __("Error"),
              message: __(error_msg[errorKey]),
              indicator: "red",
            });
            return;
          }
          frappe.call({
            method: "frappe.desk.form.save.savedocs",
            args: { doc: frm.doc, action: "Save" },
            callback: function (r) {
              $(document).trigger("save", [frm.doc]);
              frappe.call({
                method:
                  "edu_quality.api.student_application.create_student_application",
                type: "POST",
                args: { name: frm.docname },
                callback: (r) => {
                  frm.disable_form();
                  frm.disable_save();
                  if (r.message) {
                    window.location.href = r.message;
                  }
                },
              });
            },
            error: function (r) {},
          });
        });
      } else if (
        frm.doc.status === "Applied" ||
        frm.doc.status === "Enrolled" ||
        frm.doc.status === "Enrollment Pending"
      ) {
        frm.set_df_property("status", "read_only", 1);
      }
      $('.inner-group-button[data-label="Create"]').remove();
    }, 10);

    $(
      "textarea[data-fieldname='custom_cold_comment'],textarea[data-fieldname='overall_remarks'],textarea[data-fieldname='follow_up_comment'],textarea[data-fieldname='walk_in_1'],textarea[data-fieldname='walk_in_2'],textarea[data-fieldname='walk_in_3']"
    ).css({ height: "70" });
    queryWalkInAttendedBy(frm);
  },

  validate: function (frm) {
    const temp_fathers_phone = frm.doc.fathers_phone.replace(/\s/g, "");
    const re =
      /^\s*(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})(?: *x(\d+))?\s*$/;
    if (!re.test(temp_fathers_phone)) {
      frappe.msgprint({
        message: __(
          "Fathers Phone Number format is invalid, Please check the spacing is according to standard phone number spacing or none at all, and country code shouldn't be there for Indian numbers only for foreign numbers. and please make sure the number is 10 digits only before proceeding ahead"
        ),
        indicator: "red",
        title: __("Incorrect Field"),
      });
      frappe.validated = false;
    }
    if (frm.doc.next_action_date) {
      const date = new Date(frm.doc.next_action_date);
      if (date !== "Invalid Date" && date.getDay() === 0) {
        frappe.validated = false;
        frappe.msgprint({
          message: __("Next Action Date cannot be set to fall on Sunday"),
          indicator: "red",
          title: __("Incorrect Field"),
        });
      }
    }
    return true;
  },

  center: function (frm) {
    frm.set_query("class", function () {
      return {
        filters: {
          school: frm.doc.center,
        },
      };
    });
  },

  status: function (frm) {
    frm.set_query("custom_lead_sub_status", function () {
      return {
        filters: {
          type: frm.doc.status,
        },
      };
    });
  },
});
