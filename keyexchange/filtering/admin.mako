<html>
 <body>
   <h1>Blacklisted IPs</h1>
   <form action="${admin_page}" method="POST">
    %for ip in ips:
      <div>${ip} <input type="checkbox" name="${ip}"></input></div>
    %endfor
    <input type="submit"></input>
   </form>
 </body>
</html>
