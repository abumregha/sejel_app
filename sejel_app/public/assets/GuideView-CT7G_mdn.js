import{c as s,a as t,F as e,h as i,o as r,t as g}from"./index-DzJS0Qci.js";const c={class:"max-w-4xl mx-auto"},l={class:"space-y-6"},a={class:"font-bold text-lg mb-3"},d=["innerHTML"],x={__name:"GuideView",setup(_){const p=[{id:1,icon:"🏗️",title:"إعداد المحطة",content:`
    <p><strong>1.</strong> اذهب إلى <strong>المحطات</strong> واضغط <strong>+ إضافة محطة</strong></p>
    <p><strong>2.</strong> املأ الاسم والعنوان ونوع العلاقة</p>
    <p><strong>3.</strong> أضف <strong>الجزر</strong> ثم <strong>المضخات</strong> ثم <strong>العدادات</strong> لكل مضخة</p>
    <p><strong>4.</strong> أضف <strong>الخزانات</strong> وحدد نوع الوقود لكل خزان</p>
    <p><strong>5.</strong> ربط كل عداد بخزانه المناسب</p>
  `},{id:2,icon:"👥",title:"إضافة الموظفين",content:`
    <p>اذهب إلى <strong>الموظفين</strong> واضغط <strong>+ إضافة موظف</strong></p>
    <p>حدد الاسم والمنصب والمحطة</p>
  `},{id:3,icon:"📋",title:"تعريف المناوبات",content:`
    <p>اذهب إلى <strong>تعريفات المناوبات</strong></p>
    <p>حدد الاسم ووقت البدء والانتهاء والأيام والمحطة والجزيرة</p>
    <p>التعريفات تتكرر تلقائياً حسب الأيام المحددة</p>
  `},{id:4,icon:"🔄",title:"إنشاء مناوبة وتسجيل القراءات",content:`
    <p><strong>1.</strong> اذهب إلى <strong>المناوبات</strong> واضغط <strong>+ إضافة مناوبة</strong></p>
    <p><strong>2.</strong> حدد المحطة والتاريخ والمناوب</p>
    <p><strong>3.</strong> افتح المناوبة واضغط <strong>+ إضافة قراءات</strong></p>
    <p><strong>4.</strong> لكل عداد: املأ قراءة الافتتاح (احذر من فجوات العداد)</p>
    <p><strong>5.</strong> عند الانتهاء: أعد فتح الصفحة وأكمل قراءات الاختتام</p>
    <p><strong>6.</strong> اضغط <strong>إقفال المناوبة</strong> لإنشاء التسوية المالية</p>
  `},{id:5,icon:"💰",title:"التحصيل والمصروفات",content:`
    <p>التحصيل النقدي والكوبونات وPOS تُسجل خلال المناوبة</p>
    <p>المصروفات تُسجل من قسم <strong>المصروفات</strong> ( agua, طعام, مصروفات أمنية, سلف موظفين)</p>
    <p>المصروفات لا تقلل المبيعات — لكنها تؤثر على صافي النقدية</p>
  `},{id:6,icon:"🛢️",title:"الشحنات والخزانات",content:`
    <p><strong>1.</strong> سجّل قراءة الخزان <strong>قبل</strong> التوريد</p>
    <p><strong>2.</strong> أضف الشحنة مع الكمية المتوقعة</p>
    <p><strong>3.</strong> سجّل قراءة الخزان <strong>بعد</strong> التوريد</p>
    <p><strong>4.</strong> النظام يحسب النقص تلقائياً</p>
    <p><strong>5.</strong> النقص يُسجّل كمطالبة منفصلة — لا يقلل من مبلغ الدفع للمورد</p>
  `},{id:7,icon:"📑",title:"تسويات الكوبونات",content:`
    <p>عندما تُسلّم الكوبونات لشركة الرحلة:</p>
    <p><strong>1.</strong> اذهب إلى <strong>تسويات الكوبونات</strong></p>
    <p><strong>2.</strong> حدد عدد الكوبونات لكل فئة (5, 6, 8 د.ل)</p>
    <p><strong>3.</strong> النظام يحسب الإجمالي تلقائياً</p>
    <p><strong>4.</strong> تتبع حالة الدفع (مدفوعة / جزئية / متعارضة)</p>
  `},{id:8,icon:"📊",title:"التقارير",content:`
    <p><strong>التقرير اليومي:</strong> ملخص مبيعات وتحصيل كل المحطات ليوم معين</p>
    <p><strong>التقرير الشهري:</strong> ملخص شامل للشهر مع مقارنة المحطات</p>
    <p><strong>المخزون:</strong> حالة الخزانات وطلبات التوريد المعلقة</p>
    <p><strong>فجوات العدادات:</strong> حركة غير محسوبة بين المناوبات</p>
  `}];return(m,o)=>(r(),s("div",c,[o[0]||(o[0]=t("h2",{class:"text-xl font-bold mb-6"},"دليل الاستخدام",-1)),t("div",l,[(r(),s(e,null,i(p,n=>t("div",{key:n.id,class:"bg-white rounded-xl shadow-sm border p-6"},[t("h3",a,g(n.icon)+" "+g(n.title),1),t("div",{class:"text-sm text-gray-600 space-y-2",innerHTML:n.content},null,8,d)])),64))])]))}};export{x as default};
